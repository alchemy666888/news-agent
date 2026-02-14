from __future__ import annotations

from datetime import datetime, timezone

from .models import Event, Signal, UserProfile


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def calculate_impact(event: Event) -> float:
    return _clamp((event.magnitude_score * 0.6) + (event.source_credibility * 0.4))


def calculate_urgency(event: Event, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age_minutes = max((now - event.timestamp).total_seconds() / 60, 0)
    recency = _clamp(1 - (age_minutes / 180))
    velocity = _clamp(float(event.raw_data.get("velocity_change", 0.5)))
    return _clamp((recency * 0.7) + (velocity * 0.3))


def calculate_personal_relevance(event: Event, user: UserProfile, category_weight: float = 1.0) -> float:
    entities = set(event.entities)
    token_overlap = 1.0 if entities.intersection(user.token_watchlist) else 0.2
    wallet_overlap = 1.0 if entities.intersection(user.whale_wallets) else 0.2
    base = (token_overlap * 0.6) + (wallet_overlap * 0.4)
    return _clamp(base * category_weight)


def calculate_noise(event: Event, duplicate_penalty: float = 0.0) -> float:
    low_engagement = _clamp(1 - float(event.raw_data.get("engagement_score", 0.5)))
    noise = 0.3 + (low_engagement * 0.5) + duplicate_penalty
    return _clamp(noise, 0.1, 1.0)


def build_signal(event: Event, user: UserProfile, category_weight: float = 1.0, duplicate_penalty: float = 0.0) -> Signal:
    impact = calculate_impact(event)
    urgency = calculate_urgency(event)
    relevance = calculate_personal_relevance(event, user, category_weight)
    noise = calculate_noise(event, duplicate_penalty)
    score = _clamp((impact * urgency * relevance) / max(noise, 0.1))
    confidence = _clamp((event.source_credibility * 0.6) + ((1 - noise) * 0.4))
    reasons = [
        f"impact={impact:.2f}",
        f"urgency={urgency:.2f}",
        f"relevance={relevance:.2f}",
        f"noise={noise:.2f}",
    ]
    return Signal(
        event=event,
        impact=impact,
        urgency=urgency,
        personal_relevance=relevance,
        noise=noise,
        actionability_score=score,
        confidence_score=confidence,
        reasons=reasons,
    )
