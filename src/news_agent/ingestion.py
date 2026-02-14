from __future__ import annotations

from collections.abc import Iterable

from .models import Event
from .normalization import normalize_event


class BaseIngestor:
    source_type: str

    def ingest(self, payloads: Iterable[dict]) -> list[Event]:
        return [normalize_event(self.source_type, p) for p in payloads]


class OnChainIngestor(BaseIngestor):
    source_type = "onchain"


class NewsIngestor(BaseIngestor):
    source_type = "news"


class SocialIngestor(BaseIngestor):
    source_type = "social"
