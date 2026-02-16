from __future__ import annotations

import csv
import math
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

BTC_CSV = Path("data/btcusdt_1h_history.csv")
HYPER_CSV = Path("data/hyperliquid_position_history.csv")
OUTPUT_MD = Path("docs/trading_strategies_report.md")
HOURS_PER_YEAR = 24 * 365
COST_PER_TURNOVER = 0.0005  # 5 bps one-way


@dataclass
class StrategyResult:
    name: str
    description: str
    metrics: Dict[str, float]


def read_btc_data(path: Path) -> Dict[str, List[float]]:
    times: List[str] = []
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []
    taker_buy_base: List[float] = []

    with path.open() as f:
        for row in csv.DictReader(f):
            times.append(row["open_time_iso"])
            closes.append(float(row["close"]))
            highs.append(float(row["high"]))
            lows.append(float(row["low"]))
            volumes.append(float(row["volume"]))
            taker_buy_base.append(float(row["taker_buy_base_volume"]))

    return {
        "time": times,
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
        "taker_buy_base": taker_buy_base,
    }


def read_hyper_hourly_flow(path: Path) -> Dict[str, float]:
    hourly_flow_usd: Dict[str, float] = defaultdict(float)

    with path.open() as f:
        for row in csv.DictReader(f):
            if row["symbol"] != "BTC":
                continue
            ts = datetime.fromisoformat(row["timestamp"])
            ts_hour = ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
            side = 1.0 if row["fill_side"].lower() == "buy" else -1.0
            notional = float(row["fill_size"]) * float(row["fill_price"])
            hourly_flow_usd[ts_hour] += side * notional

    return dict(hourly_flow_usd)


def rolling_mean(values: List[float], window: int) -> List[float | None]:
    out: List[float | None] = [None] * len(values)
    q: deque[float] = deque()
    running = 0.0
    for i, v in enumerate(values):
        q.append(v)
        running += v
        if len(q) > window:
            running -= q.popleft()
        if len(q) == window:
            out[i] = running / window
    return out


def rolling_std(values: List[float], window: int) -> List[float | None]:
    out: List[float | None] = [None] * len(values)
    q: deque[float] = deque()
    running = 0.0
    running_sq = 0.0
    for i, v in enumerate(values):
        q.append(v)
        running += v
        running_sq += v * v
        if len(q) > window:
            old = q.popleft()
            running -= old
            running_sq -= old * old
        if len(q) == window:
            mean = running / window
            var = max((running_sq / window) - (mean * mean), 0.0)
            out[i] = math.sqrt(var)
    return out


def compute_rsi(closes: List[float], period: int = 14) -> List[float | None]:
    rsi: List[float | None] = [None] * len(closes)
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)

    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period

    for i in range(period + 1, len(closes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def returns_from_close(closes: List[float]) -> List[float]:
    rets = [0.0] * len(closes)
    for i in range(1, len(closes)):
        rets[i] = closes[i] / closes[i - 1] - 1.0
    return rets


def run_backtest(closes: List[float], signal: List[int], cost: float = COST_PER_TURNOVER) -> Dict[str, float]:
    assert len(closes) == len(signal)
    rets = returns_from_close(closes)
    n = len(closes)

    position = [0] * n
    strategy_rets = [0.0] * n

    for t in range(1, n):
        position[t] = signal[t - 1]
        turnover = abs(position[t] - position[t - 1])
        strategy_rets[t] = position[t] * rets[t] - turnover * cost

    equity = [1.0]
    for r in strategy_rets[1:]:
        equity.append(equity[-1] * (1.0 + r))

    total_return = equity[-1] - 1.0
    periods = max(n - 1, 1)
    years = periods / HOURS_PER_YEAR
    cagr = equity[-1] ** (1.0 / years) - 1.0 if years > 0 else 0.0

    mean_ret = sum(strategy_rets[1:]) / periods
    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in strategy_rets[1:]) / periods)
    sharpe = (mean_ret / std_ret) * math.sqrt(HOURS_PER_YEAR) if std_ret > 0 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (v / peak) - 1.0
        max_dd = min(max_dd, dd)

    trades, win_rate = trade_stats(position, strategy_rets)

    exposure = sum(abs(p) for p in position) / len(position)

    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "trades": float(trades),
        "win_rate": win_rate,
        "exposure": exposure,
    }


def trade_stats(position: List[int], strat_rets: List[float]) -> Tuple[int, float]:
    trades = 0
    wins = 0
    current_pnl = 0.0
    in_trade = False

    for i in range(1, len(position)):
        if position[i] != 0 and position[i - 1] == 0:
            trades += 1
            in_trade = True
            current_pnl = strat_rets[i]
        elif position[i] != 0 and position[i] != position[i - 1]:
            if in_trade and current_pnl > 0:
                wins += 1
            trades += 1
            in_trade = True
            current_pnl = strat_rets[i]
        elif position[i] != 0 and in_trade:
            current_pnl += strat_rets[i]
        elif position[i] == 0 and position[i - 1] != 0 and in_trade:
            current_pnl += strat_rets[i]
            if current_pnl > 0:
                wins += 1
            in_trade = False
            current_pnl = 0.0

    if in_trade:
        if current_pnl > 0:
            wins += 1

    win_rate = wins / trades if trades > 0 else 0.0
    return trades, win_rate


def build_signals(data: Dict[str, List[float]], hyper_flow: Dict[str, float]) -> List[StrategyResult]:
    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]
    time = data["time"]
    taker_buy = data["taker_buy_base"]

    results: List[StrategyResult] = []

    # Strategy 1: Trend following via SMA crossover
    sma_fast = rolling_mean(close, 50)
    sma_slow = rolling_mean(close, 200)
    signal = [0] * len(close)
    for i in range(len(close)):
        if sma_fast[i] is None or sma_slow[i] is None:
            continue
        signal[i] = 1 if sma_fast[i] > sma_slow[i] else -1
    results.append(
        StrategyResult(
            name="SMA 50/200 Trend",
            description="Long when SMA(50) > SMA(200), short otherwise.",
            metrics=run_backtest(close, signal),
        )
    )

    # Strategy 2: RSI mean reversion
    rsi = compute_rsi(close, 14)
    signal = [0] * len(close)
    for i in range(len(close)):
        if rsi[i] is None:
            continue
        if rsi[i] < 30:
            signal[i] = 1
        elif rsi[i] > 70:
            signal[i] = -1
        else:
            signal[i] = 0
    results.append(
        StrategyResult(
            name="RSI Mean Reversion",
            description="Long when RSI(14) < 30, short when RSI(14) > 70, flat in between.",
            metrics=run_backtest(close, signal),
        )
    )

    # Strategy 3: 20h breakout + volume confirmation
    vol_ma = rolling_mean(volume, 20)
    signal = [0] * len(close)
    for i in range(20, len(close)):
        lookback_high = max(high[i - 20 : i])
        lookback_low = min(low[i - 20 : i])
        if vol_ma[i] is None:
            continue
        if close[i] > lookback_high and volume[i] > 1.5 * vol_ma[i]:
            signal[i] = 1
        elif close[i] < lookback_low and volume[i] > 1.5 * vol_ma[i]:
            signal[i] = -1
    results.append(
        StrategyResult(
            name="20h Breakout + Volume",
            description="Enter on 20-hour breakout only when volume is 1.5x above 20-hour average.",
            metrics=run_backtest(close, signal),
        )
    )

    # Strategy 4: Hyperliquid BTC flow z-score signal
    flow_series = [hyper_flow.get(t, 0.0) for t in time]
    flow_mu = rolling_mean(flow_series, 24)
    flow_std = rolling_std(flow_series, 24)
    signal = [0] * len(close)
    for i in range(len(close)):
        if flow_mu[i] is None or flow_std[i] is None or flow_std[i] == 0:
            continue
        z = (flow_series[i] - flow_mu[i]) / flow_std[i]
        if z > 1.0:
            signal[i] = 1
        elif z < -1.0:
            signal[i] = -1
    results.append(
        StrategyResult(
            name="Hyperliquid Flow Momentum",
            description="Use hourly BTC net notional flow z-score from Hyperliquid fills; trade in flow direction when |z| > 1.",
            metrics=run_backtest(close, signal),
        )
    )

    # Strategy 5: Order flow imbalance on Binance taker flow
    flow_ratio = [0.0] * len(close)
    for i in range(len(close)):
        if volume[i] > 0:
            flow_ratio[i] = (2.0 * taker_buy[i] / volume[i]) - 1.0

    ratio_ma = rolling_mean(flow_ratio, 12)
    signal = [0] * len(close)
    for i in range(len(close)):
        if ratio_ma[i] is None:
            continue
        if ratio_ma[i] > 0.15:
            signal[i] = 1
        elif ratio_ma[i] < -0.15:
            signal[i] = -1
    results.append(
        StrategyResult(
            name="Taker Imbalance Momentum",
            description="Trade with 12-hour average taker buy/sell imbalance on Binance spot candles.",
            metrics=run_backtest(close, signal),
        )
    )

    return results


def format_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def write_report(data: Dict[str, List[float]], results: List[StrategyResult], output: Path) -> None:
    ranked = sorted(results, key=lambda r: r.metrics["sharpe"], reverse=True)

    benchmark_signal = [1] * len(data["close"])
    benchmark = run_backtest(data["close"], benchmark_signal, cost=0.0)

    start = data["time"][0]
    end = data["time"][-1]
    n_bars = len(data["time"])

    lines: List[str] = []
    lines.append("# Trading Strategies Report")
    lines.append("")
    lines.append("## Data used")
    lines.append(f"- BTCUSDT 1h candles: `{BTC_CSV}` ({n_bars} rows, {start} to {end}).")
    lines.append(f"- Hyperliquid position/fill history: `{HYPER_CSV}` (used for BTC flow feature).")
    lines.append(f"- Backtest assumptions: one-bar signal delay, {COST_PER_TURNOVER * 100:.02f}% transaction cost per unit turnover.")
    lines.append("")
    lines.append("## Benchmark (buy-and-hold BTC, no costs)")
    lines.append(
        f"- Total return: **{format_pct(benchmark['total_return'])}**, CAGR: **{format_pct(benchmark['cagr'])}**, "
        f"Sharpe: **{benchmark['sharpe']:.2f}**, Max drawdown: **{format_pct(benchmark['max_drawdown'])}**."
    )
    lines.append("")
    lines.append("## Strategy ideas and backtest results")
    lines.append("")
    lines.append("| Rank | Strategy | Total Return | CAGR | Sharpe | Max DD | Trades | Win Rate | Exposure |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")

    for idx, res in enumerate(ranked, start=1):
        m = res.metrics
        lines.append(
            f"| {idx} | {res.name} | {format_pct(m['total_return'])} | {format_pct(m['cagr'])} | {m['sharpe']:.2f} | "
            f"{format_pct(m['max_drawdown'])} | {int(m['trades'])} | {format_pct(m['win_rate'])} | {format_pct(m['exposure'])} |"
        )

    lines.append("")
    lines.append("## Strategy notes")
    for res in ranked:
        lines.append(f"- **{res.name}**: {res.description}")

    lines.append("")
    lines.append("## Interpretation")
    best = ranked[0]
    lines.append(
        f"- Best risk-adjusted performer in this run is **{best.name}** with Sharpe **{best.metrics['sharpe']:.2f}** "
        f"and max drawdown **{format_pct(best.metrics['max_drawdown'])}**."
    )
    lines.append("- Results are sensitive to fee/slippage assumptions and should be treated as research prototypes, not production trading advice.")
    lines.append("- Next steps: walk-forward validation, parameter sweep with out-of-sample splits, and instrumenting market-impact-aware execution.")

    output.write_text("\n".join(lines) + "\n")


def main() -> None:
    btc = read_btc_data(BTC_CSV)
    hyper = read_hyper_hourly_flow(HYPER_CSV)
    results = build_signals(btc, hyper)
    write_report(btc, results, OUTPUT_MD)
    print(f"Report written to {OUTPUT_MD}")


if __name__ == "__main__":
    main()
