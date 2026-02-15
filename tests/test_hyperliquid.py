from news_agent.hyperliquid import aggregate_trade_history, normalize_positions
from news_agent.ingestion import HyperliquidIngestor
from news_agent.models import UserProfile


def test_aggregate_trade_history_computes_realized_pnl() -> None:
    fills = [
        {"coin": "BTC", "side": "buy", "sz": "1.0", "px": "100", "fee": "0", "time": "2026-02-14T10:00:00Z", "tid": "1"},
        {"coin": "BTC", "side": "buy", "sz": "1.0", "px": "110", "fee": "0", "time": "2026-02-14T10:01:00Z", "tid": "2"},
        {"coin": "BTC", "side": "sell", "sz": "1.5", "px": "130", "fee": "1", "time": "2026-02-14T10:02:00Z", "tid": "3"},
    ]

    trades, performance = aggregate_trade_history("0xwallet", fills)

    assert len(trades) == 3
    assert round(trades[-1].entry_price, 2) == 105.0
    assert round(trades[-1].exit_price, 2) == 130.0
    assert round(trades[-1].realized_pnl, 2) == 36.5
    assert round(performance.total_realized_pnl, 2) == 36.5


def test_normalize_positions_parses_hyperliquid_state() -> None:
    state = {
        "time": 1739520000000,
        "assetPositions": [
            {"position": {"coin": "ETH", "szi": "-2", "entryPx": "2500", "markPx": "2400", "unrealizedPnl": "200"}},
        ],
    }

    positions = normalize_positions("0xwallet", state)

    assert len(positions) == 1
    assert positions[0].symbol == "ETH"
    assert positions[0].side == "short"
    assert positions[0].size == 2.0
    assert positions[0].last_updated.year == 2025


class _StubHyperliquidClient:
    def user_fills(self, wallet: str, limit: int = 200) -> list[dict]:
        return [
            {
                "coin": "BTC",
                "side": "buy",
                "sz": "0.5",
                "px": "43000",
                "fee": "2",
                "time": "2026-02-14T10:00:00Z",
                "tid": "a1",
            },
            {
                "coin": "BTC",
                "side": "sell",
                "sz": "0.25",
                "px": "43500",
                "fee": "1",
                "time": "2026-02-14T10:05:00Z",
                "tid": "a2",
            },
        ]

    def clearinghouse_state(self, wallet: str) -> dict:
        return {
            "time": "2026-02-14T10:06:00Z",
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.25",
                        "entryPx": "43000",
                        "markPx": "43600",
                        "unrealizedPnl": "150",
                    }
                }
            ],
        }

    def frontend_open_orders(self, wallet: str) -> list[dict]:
        return [{"oid": "123"}]

    def open_orders(self, wallet: str) -> list[dict]:
        return []


def test_hyperliquid_ingestor_emits_position_trade_and_performance_payloads() -> None:
    ingestor = HyperliquidIngestor(client=_StubHyperliquidClient())
    user = UserProfile(
        token_watchlist={"BTC"},
        whale_wallets=set(),
        hyperliquid_wallets={"0xwallet"},
        alert_threshold=0.4,
    )

    payloads = ingestor.fetch_latest(user, limit=20)

    event_types = {payload.get("event_type") for payload in payloads}
    assert "position_snapshot" in event_types
    assert "fill" in event_types
    assert "wallet_performance" in event_types
