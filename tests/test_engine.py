from news_agent.engine import IntelligenceEngine
from news_agent.models import UserProfile


def test_run_cycle_produces_ranked_signals_and_alerts() -> None:
    profile = UserProfile(token_watchlist={"BTC"}, whale_wallets=set(), alert_threshold=0.45)
    engine = IntelligenceEngine(profile)
    streams = {
        "onchain": [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "summary": "BTC whale moved large funds",
                "magnitude_score": 0.95,
                "source_credibility": 0.9,
                "engagement_score": 0.8,
                "velocity_change": 0.8,
            }
        ],
        "news": [
            {
                "timestamp": "2026-01-01T00:01:00Z",
                "title": "BTC gains momentum",
                "magnitude_score": 0.6,
                "source_credibility": 0.7,
            }
        ],
        "social": [],
    }

    signals, alerts = engine.run_cycle(streams)

    assert len(signals) == 2
    assert signals[0].actionability_score >= signals[1].actionability_score
    assert alerts


def test_deduplicate_removes_identical_items() -> None:
    profile = UserProfile(token_watchlist={"ETH"}, whale_wallets=set(), alert_threshold=0.1)
    engine = IntelligenceEngine(profile)
    payload = {
        "timestamp": "2026-01-01T00:00:00Z",
        "summary": "ETH exchange inflow surge",
        "magnitude_score": 0.9,
        "source_credibility": 0.8,
    }
    streams = {"onchain": [payload, payload], "news": [], "social": []}

    signals, _ = engine.run_cycle(streams)
    assert len(signals) == 1
