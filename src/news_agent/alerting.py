from __future__ import annotations

from dataclasses import dataclass

from .models import Signal, UserProfile


@dataclass(slots=True)
class Alert:
    title: str
    bullets: list[str]
    confidence_score: float
    source_links: list[str]
    why_this_matters: str


def should_alert(signal: Signal, user: UserProfile) -> bool:
    high_value_whale = signal.event.source_type == "onchain" and signal.event.magnitude_score >= 0.85
    pnl_value = abs(float(signal.event.raw_data.get("realized_pnl", 0.0))) + abs(
        float(signal.event.raw_data.get("unrealized_pnl", 0.0))
    )
    high_value_hyperliquid = signal.event.source_type == "hyperliquid" and pnl_value >= 10_000
    return signal.actionability_score >= user.alert_threshold or high_value_whale or high_value_hyperliquid


def build_alert(signal: Signal) -> Alert:
    payload = signal.event.raw_data
    links = payload.get("source_links", [])
    bullets = [
        f"Signal score: {signal.actionability_score:.2f}",
        f"Entities: {', '.join(signal.event.entities) if signal.event.entities else 'n/a'}",
        f"Sentiment: {signal.event.sentiment_score:.2f}",
        f"Source type: {signal.event.source_type}",
    ]
    return Alert(
        title=signal.event.summary[:120],
        bullets=bullets,
        confidence_score=signal.confidence_score,
        source_links=list(links),
        why_this_matters="This event combines impact, urgency, and your preferences with low estimated noise.",
    )
