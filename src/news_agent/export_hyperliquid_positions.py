from __future__ import annotations

import argparse
import csv
import os
import re
import socket

from .hyperliquid import HyperliquidInfoClient, PositionHistoryRow, reconstruct_position_history

WALLET_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}")


def load_dotenv(path: str = ".env") -> None:
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


def wallets_from_env(raw_wallets: str) -> list[str]:
    matches = WALLET_PATTERN.findall(raw_wallets)
    seen: set[str] = set()
    wallets: list[str] = []
    for wallet in matches:
        lowered = wallet.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        wallets.append(wallet)
    return wallets


def check_hyperliquid_dns(host: str = "api.hyperliquid.xyz") -> bool:
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror:
        return False
    return True


def write_history_csv(path: str, rows: list[PositionHistoryRow]) -> None:
    fieldnames = [
        "wallet",
        "timestamp",
        "trade_id",
        "symbol",
        "fill_side",
        "fill_size",
        "fill_price",
        "fee",
        "position_side",
        "position_size",
        "avg_entry_price",
        "realized_pnl",
        "cumulative_realized_pnl",
        "cumulative_fees",
    ]

    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "wallet": row.wallet,
                    "timestamp": row.timestamp.isoformat(),
                    "trade_id": row.trade_id,
                    "symbol": row.symbol,
                    "fill_side": row.fill_side,
                    "fill_size": f"{row.fill_size:.10f}",
                    "fill_price": f"{row.fill_price:.10f}",
                    "fee": f"{row.fee:.10f}",
                    "position_side": row.position_side,
                    "position_size": f"{row.position_size:.10f}",
                    "avg_entry_price": f"{row.avg_entry_price:.10f}",
                    "realized_pnl": f"{row.realized_pnl:.10f}",
                    "cumulative_realized_pnl": f"{row.cumulative_realized_pnl:.10f}",
                    "cumulative_fees": f"{row.cumulative_fees:.10f}",
                }
            )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Export Hyperliquid position history to CSV")
    parser.add_argument(
        "--output",
        default=os.getenv("NEWS_AGENT_HL_POSITION_HISTORY_CSV", "hyperliquid_position_history.csv"),
        help="Output CSV file path.",
    )
    parser.add_argument(
        "--fill-limit",
        type=int,
        default=max(50, int(os.getenv("NEWS_AGENT_HL_FILL_LIMIT", "1000"))),
        help="Max number of fills to fetch per wallet.",
    )
    args = parser.parse_args()

    wallets = wallets_from_env(os.getenv("NEWS_AGENT_HYPERLIQUID_WALLETS", ""))
    if not wallets:
        raise RuntimeError("NEWS_AGENT_HYPERLIQUID_WALLETS is empty or contains no valid wallet addresses.")

    client = HyperliquidInfoClient(info_url=os.getenv("HYPERLIQUID_INFO_URL", "https://api.hyperliquid.xyz/info"))
    all_rows: list[PositionHistoryRow] = []

    for wallet in wallets:
        fills = client.user_fills(wallet, limit=max(1, args.fill_limit))
        rows = reconstruct_position_history(wallet, fills)
        all_rows.extend(rows)

    all_rows.sort(key=lambda row: row.timestamp)
    write_history_csv(args.output, all_rows)

    print(f"wallets={len(wallets)}")
    print(f"rows={len(all_rows)}")
    print(f"output={args.output}")
    if not check_hyperliquid_dns():
        print("warning=api.hyperliquid.xyz DNS resolution failed in current environment")


if __name__ == "__main__":
    main()
