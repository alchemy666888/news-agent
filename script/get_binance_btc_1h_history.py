#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000
ONE_HOUR_MS = 60 * 60 * 1000
USER_AGENT = "news-agent/binance-btc-1h-exporter"


def parse_time_to_ms(value: str | None, default_ms: int) -> int:
    if not value:
        return default_ms

    clean = value.strip()
    if not clean:
        return default_ms

    if clean.isdigit():
        numeric = int(clean)
        if numeric > 10_000_000_000:
            return numeric
        return numeric * 1000

    iso_candidate = clean.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
    except ValueError:
        dt = datetime.strptime(clean, "%Y-%m-%d")
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

    return int(dt.timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()


def fetch_klines(symbol: str, start_ms: int, end_ms: int, limit: int) -> list[list[Any]]:
    params = {
        "symbol": symbol,
        "interval": "1h",
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": min(max(limit, 1), MAX_LIMIT),
    }
    url = f"{BINANCE_KLINES_URL}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Binance response: {data!r}")
    return data


def collect_1h_history(symbol: str, start_ms: int, end_ms: int, request_limit: int, sleep_seconds: float) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start_ms

    while cursor < end_ms:
        batch = fetch_klines(symbol=symbol, start_ms=cursor, end_ms=end_ms, limit=request_limit)
        if not batch:
            break

        rows.extend(batch)
        last_open_ms = int(batch[-1][0])
        next_cursor = last_open_ms + ONE_HOUR_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    deduped: dict[int, list[Any]] = {}
    for row in rows:
        open_ms = int(row[0])
        deduped[open_ms] = row
    return [deduped[key] for key in sorted(deduped)]


def write_csv(rows: list[list[Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "open_time_iso",
                "open_time_ms",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time_iso",
                "close_time_ms",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base_volume",
                "taker_buy_quote_volume",
            ]
        )
        for row in rows:
            open_ms = int(row[0])
            close_ms = int(row[6])
            writer.writerow(
                [
                    ms_to_iso(open_ms),
                    open_ms,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    ms_to_iso(close_ms),
                    close_ms,
                    row[7],
                    row[8],
                    row[9],
                    row[10],
                ]
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download BTCUSDT 1-hour historical price and volume data from Binance public API."
    )
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair symbol (default: BTCUSDT).")
    parser.add_argument(
        "--start",
        default="2017-08-17",
        help="Start time (YYYY-MM-DD, ISO-8601, unix seconds, or unix milliseconds).",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End time (YYYY-MM-DD, ISO-8601, unix seconds, or unix milliseconds). Defaults to now.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_LIMIT,
        help=f"Per-request kline limit (1-{MAX_LIMIT}, default: {MAX_LIMIT}).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.15,
        help="Delay between paginated requests to avoid hitting rate limits.",
    )
    parser.add_argument(
        "--output",
        default="script/btcusdt_1h_history.csv",
        help="Output CSV path (default: script/btcusdt_1h_history.csv).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = parse_time_to_ms(args.start, default_ms=now_ms - ONE_HOUR_MS * 24 * 30)
    end_ms = parse_time_to_ms(args.end, default_ms=now_ms)

    if end_ms <= start_ms:
        raise RuntimeError("--end must be greater than --start.")

    rows = collect_1h_history(
        symbol=args.symbol.upper(),
        start_ms=start_ms,
        end_ms=end_ms,
        request_limit=args.limit,
        sleep_seconds=max(args.sleep_seconds, 0.0),
    )
    output_path = Path(args.output)
    write_csv(rows, output_path)

    print(f"symbol={args.symbol.upper()}")
    print(f"start={ms_to_iso(start_ms)}")
    print(f"end={ms_to_iso(end_ms)}")
    print(f"candles={len(rows)}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
