from news_agent.export_hyperliquid_positions import wallets_from_env
from news_agent.hyperliquid import aggregate_trade_history, normalize_positions, reconstruct_position_history
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


def test_reconstruct_position_history_tracks_running_state() -> None:
    fills = [
        {"coin": "ETH", "side": "buy", "sz": "2.0", "px": "1000", "fee": "1", "time": "2026-02-14T10:00:00Z", "tid": "1"},
        {"coin": "ETH", "side": "sell", "sz": "1.0", "px": "1100", "fee": "1", "time": "2026-02-14T10:01:00Z", "tid": "2"},
        {"coin": "ETH", "side": "sell", "sz": "1.0", "px": "900", "fee": "1", "time": "2026-02-14T10:02:00Z", "tid": "3"},
    ]

    rows = reconstruct_position_history("0xwallet", fills)

    assert len(rows) == 3
    assert rows[0].position_side == "long"
    assert rows[0].position_size == 2.0
    assert rows[1].position_size == 1.0
    assert rows[2].position_side == "flat"
    assert rows[2].cumulative_fees == 3.0


def test_wallets_from_env_extracts_and_dedupes_addresses() -> None:
    raw = (
        "0x1111111111111111111111111111111111111111,"
        "0x2222222222222222222222222222222222222222"
        "0x3333333333333333333333333333333333333333,"
        "0x1111111111111111111111111111111111111111"
    )
    wallets = wallets_from_env(raw)

    assert wallets == [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0x3333333333333333333333333333333333333333",
    ]
