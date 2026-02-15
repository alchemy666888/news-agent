from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import re
from typing import Any

from .models import Event

TOKEN_PATTERN = re.compile(r"\b[A-Z]{2,6}\b")
WALLET_PATTERN = re.compile(r"0x[a-fA-F0-9]{8,40}")


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric = numeric / 1000
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    if isinstance(value, str):
        clean = value.strip()
        if clean.isdigit():
            numeric = int(clean)
            if numeric > 10_000_000_000:
                return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc)
            return datetime.fromtimestamp(numeric, tz=timezone.utc)

        iso_candidate = clean.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(iso_candidate).astimezone(timezone.utc)
        except ValueError:
            parsed = parsedate_to_datetime(clean)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    raise ValueError("Unsupported timestamp format")


def extract_entities(text: str) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text.upper())
    wallets = WALLET_PATTERN.findall(text)
    entities = sorted({*tokens, *wallets})
    return entities


def duplicate_key(source_type: str, summary: str, entities: list[str]) -> str:
    normalized = f"{source_type}|{summary.strip().lower()}|{'/'.join(sorted(entities))}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def normalize_event(source_type: str, payload: dict[str, Any]) -> Event:
    summary = str(payload.get("summary") or payload.get("title") or payload.get("text") or "")
    entities = payload.get("entities") or extract_entities(summary)
    event = Event(
        source_type=source_type,
        timestamp=parse_timestamp(payload.get("timestamp")),
        entities=list(entities),
        summary=summary,
        raw_data=payload,
        sentiment_score=float(payload.get("sentiment_score", 0.0)),
        magnitude_score=float(payload.get("magnitude_score", 0.5)),
        source_credibility=float(payload.get("source_credibility", 0.5)),
    )
    event.duplicate_key = duplicate_key(source_type, event.summary, event.entities)
    return event
