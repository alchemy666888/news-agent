from __future__ import annotations

import json

from .engine import IntelligenceEngine
from .models import UserProfile


def main() -> None:
    user = UserProfile(
        token_watchlist={"BTC", "ETH", "SOL"},
        whale_wallets={"0xABCDEF1234"},
        alert_threshold=0.55,
    )
    engine = IntelligenceEngine(user)
    sample_streams = {
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
    }

    signals, alerts = engine.run_cycle(sample_streams)
    output = {
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
