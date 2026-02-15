from __future__ import annotations

import argparse
import json
import os

from .engine import IntelligenceEngine
from .models import UserProfile, utcnow


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            entry = line.strip()
            if not entry or entry.startswith("#") or "=" not in entry:
                continue

            key, raw_value = entry.split("=", maxsplit=1)
            key = key.strip()
            value = raw_value.strip()
            if not key:
                continue

            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            os.environ.setdefault(key, value)


def _sample_streams() -> dict[str, list[dict]]:
    return {
        "onchain": [
            {
                "timestamp": "2026-02-01T12:00:00Z",
                "summary": "Whale moved 120M USDT to exchange, BTC mention rising",
                "magnitude_score": 0.95,
                "source_credibility": 0.9,
                "engagement_score": 0.7,
                "velocity_change": 0.8,
                "source_links": ["https://example.com/onchain/1"],
            }
        ],
        "news": [
            {
                "timestamp": "2026-02-01T12:02:00Z",
                "title": "ETF optimism sends BTC sentiment higher",
                "sentiment_score": 0.6,
                "magnitude_score": 0.65,
                "source_credibility": 0.8,
                "engagement_score": 0.6,
                "source_links": ["https://example.com/news/1"],
            }
        ],
        "social": [
            {
                "timestamp": "2026-02-01T12:03:00Z",
                "text": "SOL volume spikes 180% in 30m",
                "sentiment_score": 0.5,
                "magnitude_score": 0.8,
                "source_credibility": 0.55,
                "engagement_score": 0.9,
                "velocity_change": 0.9,
                "source_links": ["https://example.com/social/1"],
            }
        ],
        "hyperliquid": [
            {
                "timestamp": "2026-02-01T12:04:00Z",
                "summary": "Hyperliquid 0xABCD...1234 BTC long 2.5000 @ 43100.00, uPnL +14250.00",
                "entities": ["0xABCDEF1234", "BTC", "HYPERLIQUID"],
                "sentiment_score": 0.2,
                "magnitude_score": 0.95,
                "source_credibility": 0.9,
                "engagement_score": 0.74,
                "velocity_change": 0.82,
                "source_links": ["https://app.hyperliquid.xyz/trader/0xABCDEF1234"],
                "event_type": "position_snapshot",
                "unrealized_pnl": 14250.0,
            }
        ],
    }


def _split_csv(raw: str | None, uppercase: bool = False) -> set[str]:
    if not raw:
        return set()
    values = {part.strip() for part in raw.split(",") if part.strip()}
    if uppercase:
        return {value.upper() for value in values}
    return values


def _build_user_profile() -> UserProfile:
    watchlist = _split_csv(os.getenv("NEWS_AGENT_WATCHLIST"), uppercase=True) or {"BTC", "ETH", "SOL"}
    wallets = _split_csv(os.getenv("NEWS_AGENT_WHALE_WALLETS"))
    hyperliquid_wallets = _split_csv(os.getenv("NEWS_AGENT_HYPERLIQUID_WALLETS")) or set(wallets)
    try:
        threshold = float(os.getenv("NEWS_AGENT_ALERT_THRESHOLD", "0.55"))
    except ValueError:
        threshold = 0.55
    threshold = max(0.0, min(1.0, threshold))
    return UserProfile(
        token_watchlist=watchlist,
        whale_wallets=wallets,
        hyperliquid_wallets=hyperliquid_wallets,
        alert_threshold=threshold,
    )


def _fetch_limit(default_value: int = 25) -> int:
    try:
        return max(1, int(os.getenv("NEWS_AGENT_FETCH_LIMIT", str(default_value))))
    except ValueError:
        return default_value


def main() -> None:
    _load_dotenv()

    parser = argparse.ArgumentParser(description="Crypto-first intelligence agent")
    parser.add_argument(
        "--mode",
        choices=("live", "demo"),
        default=os.getenv("NEWS_AGENT_MODE", "live"),
        help="Use live ingestion sources or demo sample payloads.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_fetch_limit(),
        help="Maximum number of raw payloads fetched per source in live mode.",
    )
    parser.add_argument(
        "--strict-live",
        action="store_true",
        help="Fail when live mode returns zero events instead of falling back to demo data.",
    )
    args = parser.parse_args()

    user = _build_user_profile()
    engine = IntelligenceEngine(user)

    if args.mode == "live":
        streams = engine.collect_live_streams(limit_per_source=max(args.limit, 1))
        if not any(streams.values()):
            if args.strict_live:
                raise RuntimeError(
                    "Live ingestion returned no events. Configure NEWS_AGENT_NEWS_FEEDS and/or ETHERSCAN_API_KEY."
                )
            mode = "demo-fallback"
            streams = _sample_streams()
        else:
            mode = "live"
    else:
        mode = "demo"
        streams = _sample_streams()

    signals, alerts = engine.run_cycle(streams)
    output = {
        "mode": mode,
        "generated_at": utcnow().isoformat(),
        "stream_counts": {source: len(payloads) for source, payloads in streams.items()},
        "signals": [
            {
                "summary": s.event.summary,
                "score": round(s.actionability_score, 3),
                "confidence": round(s.confidence_score, 3),
                "reasons": s.reasons,
            }
            for s in signals
        ],
        "alerts": [
            {
                "title": a.title,
                "confidence": round(a.confidence_score, 3),
                "bullets": a.bullets,
            }
            for a in alerts
        ],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
