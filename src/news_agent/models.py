from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Event:
    source_type: str
    timestamp: datetime
    entities: list[str]
    summary: str
    raw_data: dict[str, Any]
    sentiment_score: float
    magnitude_score: float
    source_credibility: float = 0.5
    duplicate_key: str = ""


@dataclass(slots=True)
class UserProfile:
    token_watchlist: set[str] = field(default_factory=set)
    whale_wallets: set[str] = field(default_factory=set)
    hyperliquid_wallets: set[str] = field(default_factory=set)
    alert_threshold: float = 0.6


@dataclass(slots=True)
class Signal:
    event: Event
    impact: float
    urgency: float
    personal_relevance: float
    noise: float
    actionability_score: float
    confidence_score: float
    reasons: list[str]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
