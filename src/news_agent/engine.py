from __future__ import annotations

from collections import Counter

from .alerting import Alert, build_alert, should_alert
from .ingestion import HyperliquidIngestor, NewsIngestor, OnChainIngestor, SocialIngestor
from .models import Event, Signal, UserProfile
from .personalization import PersonalizationModel
from .scoring import build_signal


class IntelligenceEngine:
    def __init__(self, user_profile: UserProfile) -> None:
        self.user_profile = user_profile
        self.personalization = PersonalizationModel()
        self.ingestors = {
            "onchain": OnChainIngestor(),
            "news": NewsIngestor(),
            "social": SocialIngestor(),
            "hyperliquid": HyperliquidIngestor(),
        }

    def ingest_all(self, streams: dict[str, list[dict]]) -> list[Event]:
        events: list[Event] = []
        for source_type, payloads in streams.items():
            ingestor = self.ingestors[source_type]
            events.extend(ingestor.ingest(payloads))
        return self._deduplicate(events)

    def collect_live_streams(self, limit_per_source: int = 25) -> dict[str, list[dict]]:
        streams: dict[str, list[dict]] = {}
        for source_type, ingestor in self.ingestors.items():
            streams[source_type] = ingestor.fetch_latest(self.user_profile, limit_per_source)
        return streams

    def _deduplicate(self, events: list[Event]) -> list[Event]:
        seen: set[str] = set()
        deduped: list[Event] = []
        for event in sorted(events, key=lambda e: e.timestamp, reverse=True):
            if event.duplicate_key in seen:
                continue
            seen.add(event.duplicate_key)
            deduped.append(event)
        return deduped

    def score_events(self, events: list[Event]) -> list[Signal]:
        source_counts = Counter(e.source_type for e in events)
        signals: list[Signal] = []
        for event in events:
            weight = self.personalization.weight_for(event.source_type)
            duplicate_penalty = 0.2 if source_counts[event.source_type] > 8 else 0.0
            signals.append(build_signal(event, self.user_profile, weight, duplicate_penalty))
        return sorted(signals, key=lambda s: s.actionability_score, reverse=True)

    def generate_alerts(self, signals: list[Signal]) -> list[Alert]:
        return [build_alert(s) for s in signals if should_alert(s, self.user_profile)]

    def run_cycle(self, streams: dict[str, list[dict]]) -> tuple[list[Signal], list[Alert]]:
        events = self.ingest_all(streams)
        signals = self.score_events(events)
        alerts = self.generate_alerts(signals)
        return signals, alerts

    def run_live_cycle(self, limit_per_source: int = 25) -> tuple[list[Signal], list[Alert], dict[str, list[dict]]]:
        streams = self.collect_live_streams(limit_per_source)
        signals, alerts = self.run_cycle(streams)
        return signals, alerts, streams
