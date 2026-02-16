from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

BTC_CSV = Path("data/btcusdt_1h_history.csv")
HYPER_CSV = Path("data/hyperliquid_position_history.csv")
OUTPUT_MD = Path("docs/smart_wallet_strategy_backtest.md")
HOURS_PER_YEAR = 24 * 365
COST_PER_TURNOVER = 0.0005  # 5 bps one-way
TRAIN_RATIO = 0.7
MIN_ACTIVE_HOURS = 8
TOP_WALLETS = 8


@dataclass
class WalletStat:
    wallet: str
    active_hours: int
    hit_rate: float
    sharpe: float
    total_return: float
    weight: float


@dataclass
class BacktestResult:
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    trades: int
    win_rate: float
    exposure: float


def read_btc_data(path: Path) -> Dict[str, List[float]]:
    times: List[str] = []
    closes: List[float] = []

    with path.open() as f:
        for row in csv.DictReader(f):
            times.append(row["open_time_iso"])
            closes.append(float(row["close"]))

    return {"time": times, "close": closes}


def read_wallet_btc_hourly_flow(path: Path) -> Dict[str, Dict[str, float]]:
    wallet_hour_flow: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    with path.open() as f:
        for row in csv.DictReader(f):
            if row["symbol"] != "BTC":
                continue
            wallet = row["wallet"]
            ts = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)
            hour = ts.replace(minute=0, second=0, microsecond=0).isoformat()
            side = 1.0 if row["fill_side"].lower() == "buy" else -1.0
            notional = float(row["fill_size"]) * float(row["fill_price"])
            wallet_hour_flow[wallet][hour] += side * notional

    return {wallet: dict(hour_map) for wallet, hour_map in wallet_hour_flow.items()}


def returns_from_close(closes: List[float]) -> List[float]:
    rets = [0.0] * len(closes)
    for i in range(1, len(closes)):
        rets[i] = closes[i] / closes[i - 1] - 1.0
    return rets


def run_backtest(closes: List[float], signal: List[int], cost: float = COST_PER_TURNOVER) -> BacktestResult:
    if len(closes) != len(signal):
        raise ValueError("closes and signal must be same length")

    rets = returns_from_close(closes)
    n = len(closes)
    position = [0] * n
    strat_rets = [0.0] * n

    for i in range(1, n):
        position[i] = signal[i - 1]  # one-bar delay
        turnover = abs(position[i] - position[i - 1])
        strat_rets[i] = position[i] * rets[i] - turnover * cost

    equity = [1.0]
    for r in strat_rets[1:]:
        equity.append(equity[-1] * (1.0 + r))

    periods = max(1, n - 1)
    years = periods / HOURS_PER_YEAR
    total_return = equity[-1] - 1.0
    cagr = equity[-1] ** (1.0 / years) - 1.0 if years > 0 else 0.0

    mean_ret = sum(strat_rets[1:]) / periods
    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in strat_rets[1:]) / periods)
    sharpe = (mean_ret / std_ret) * math.sqrt(HOURS_PER_YEAR) if std_ret > 0 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak) - 1.0)

    trades, win_rate = trade_stats(position, strat_rets)
    exposure = sum(abs(p) for p in position) / len(position)

    return BacktestResult(
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_dd,
        trades=trades,
        win_rate=win_rate,
        exposure=exposure,
    )


def trade_stats(position: List[int], strat_rets: List[float]) -> Tuple[int, float]:
    trades = 0
    wins = 0
    in_trade = False
    current_pnl = 0.0

    for i in range(1, len(position)):
        if position[i] != 0 and position[i - 1] == 0:
            trades += 1
            in_trade = True
            current_pnl = strat_rets[i]
        elif position[i] != 0 and position[i] != position[i - 1]:
            if in_trade and current_pnl > 0:
                wins += 1
            trades += 1
            current_pnl = strat_rets[i]
        elif position[i] != 0 and in_trade:
            current_pnl += strat_rets[i]
        elif position[i] == 0 and position[i - 1] != 0 and in_trade:
            current_pnl += strat_rets[i]
            if current_pnl > 0:
                wins += 1
            in_trade = False
            current_pnl = 0.0

    if in_trade and current_pnl > 0:
        wins += 1

    return trades, (wins / trades if trades > 0 else 0.0)


def wallet_flow_signal(flow: float) -> int:
    if flow > 0:
        return 1
    if flow < 0:
        return -1
    return 0


def evaluate_wallet(
    wallet: str,
    flow_by_hour: Dict[str, float],
    times: List[str],
    closes: List[float],
    train_end_idx: int,
) -> WalletStat | None:
    wallet_signal = [wallet_flow_signal(flow_by_hour.get(ts, 0.0)) for ts in times]
    active_hours = sum(1 for s in wallet_signal[:train_end_idx] if s != 0)

    if active_hours < MIN_ACTIVE_HOURS:
        return None

    train_bt = run_backtest(closes[:train_end_idx], wallet_signal[:train_end_idx])
    rets = returns_from_close(closes)

    correct = 0
    total = 0
    for i in range(1, train_end_idx):
        prev_sig = wallet_signal[i - 1]
        if prev_sig == 0:
            continue
        total += 1
        if prev_sig * rets[i] > 0:
            correct += 1

    hit_rate = correct / total if total > 0 else 0.0
    edge = max(hit_rate - 0.5, 0.0)
    score = edge * math.sqrt(active_hours)

    return WalletStat(
        wallet=wallet,
        active_hours=active_hours,
        hit_rate=hit_rate,
        sharpe=train_bt.sharpe,
        total_return=train_bt.total_return,
        weight=score,
    )


def build_combined_signal(
    wallet_stats: Iterable[WalletStat],
    wallet_flow: Dict[str, Dict[str, float]],
    times: List[str],
    threshold: float,
) -> List[int]:
    stats = list(wallet_stats)
    total_weight = sum(w.weight for w in stats)
    if total_weight <= 0:
        return [0] * len(times)

    norm_weights = {w.wallet: w.weight / total_weight for w in stats}
    signal = [0] * len(times)

    for i, ts in enumerate(times):
        score = 0.0
        for wallet, w in norm_weights.items():
            score += w * wallet_flow_signal(wallet_flow[wallet].get(ts, 0.0))
        if score > threshold:
            signal[i] = 1
        elif score < -threshold:
            signal[i] = -1

    return signal


def format_pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def select_wallets(
    wallet_flow: Dict[str, Dict[str, float]], times: List[str], closes: List[float], train_end_idx: int
) -> List[WalletStat]:
    stats: List[WalletStat] = []
    for wallet, flow in wallet_flow.items():
        s = evaluate_wallet(wallet, flow, times, closes, train_end_idx)
        if s is not None:
            stats.append(s)

    stats.sort(key=lambda x: (x.weight, x.sharpe), reverse=True)
    selected = [s for s in stats if s.weight > 0][:TOP_WALLETS]
    return selected


def write_report(
    output: Path,
    times: List[str],
    closes: List[float],
    selected_wallets: List[WalletStat],
    threshold: float,
    train_end_idx: int,
    wallet_flow: Dict[str, Dict[str, float]],
) -> None:
    start = times[0]
    end = times[-1]
    n = len(times)

    weighted_signal = build_combined_signal(selected_wallets, wallet_flow, times, threshold)
    equal_wallets = [WalletStat(**{**w.__dict__, "weight": 1.0}) for w in selected_wallets]
    equal_signal = build_combined_signal(equal_wallets, wallet_flow, times, threshold)
    buy_hold_signal = [1] * len(closes)

    full_weighted = run_backtest(closes, weighted_signal)
    full_equal = run_backtest(closes, equal_signal)
    full_buy_hold = run_backtest(closes, buy_hold_signal, cost=0.0)

    oos_closes = closes[train_end_idx - 1 :]
    oos_weighted_signal = weighted_signal[train_end_idx - 1 :]
    oos_equal_signal = equal_signal[train_end_idx - 1 :]
    oos_buy_hold = [1] * len(oos_closes)

    oos_weighted = run_backtest(oos_closes, oos_weighted_signal)
    oos_equal = run_backtest(oos_closes, oos_equal_signal)
    oos_bh = run_backtest(oos_closes, oos_buy_hold, cost=0.0)

    lines: List[str] = []
    lines.append("# Smart Wallet BTC Strategy & Backtest")
    lines.append("")
    lines.append("## 1) Data and objective")
    lines.append(f"- BTC hourly candles from `{BTC_CSV}`; sample analyzed: **{start} to {end}** ({n} bars).")
    lines.append(f"- Smart-wallet trades from `{HYPER_CSV}` (BTC fills only, aggregated to hourly net signed notional).")
    lines.append("- Goal: rank wallets by in-sample predictive quality, then follow a weighted consensus signal.")
    lines.append("")
    lines.append("## 2) Methodology")
    lines.append("1. Convert each wallet's hourly BTC flow into a direction signal: buy=+1, sell=-1, no trade=0.")
    lines.append("2. Use the first 70% of the overlapping sample as **training**, remaining 30% as **out-of-sample test**.")
    lines.append("3. For each wallet, compute in-sample performance when naively copying that wallet with one-bar delay and 5 bps one-way cost.")
    lines.append("4. Wallet score = `max(hit_rate - 50%, 0) * sqrt(active_hours)`; select top wallets with positive score.")
    lines.append("5. Build portfolio consensus score per hour: weighted sum of selected wallet directions.")
    lines.append(f"6. Trading rule: long if consensus > {threshold:.2f}, short if consensus < -{threshold:.2f}, else flat.")
    lines.append("")
    lines.append("## 3) Selected smart wallets and weights")
    if selected_wallets:
        total_w = sum(w.weight for w in selected_wallets)
        lines.append("")
        lines.append("| Wallet | Train Active Hours | Train Hit Rate | Train Sharpe | Train Return | Portfolio Weight |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for w in selected_wallets:
            pw = w.weight / total_w if total_w > 0 else 0.0
            lines.append(
                f"| `{w.wallet}` | {w.active_hours} | {format_pct(w.hit_rate)} | {w.sharpe:.2f} | {format_pct(w.total_return)} | {format_pct(pw)} |"
            )
    else:
        lines.append("- No wallets passed selection; weighted strategy is flat.")

    lines.append("")
    lines.append("## 4) Backtest results")
    lines.append("")
    lines.append("### Full period")
    lines.append("| Strategy | Total Return | CAGR | Sharpe | Max Drawdown | Trades | Win Rate | Exposure |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| Weighted smart-wallet consensus | {format_pct(full_weighted.total_return)} | {format_pct(full_weighted.cagr)} | {full_weighted.sharpe:.2f} | {format_pct(full_weighted.max_drawdown)} | {full_weighted.trades} | {format_pct(full_weighted.win_rate)} | {format_pct(full_weighted.exposure)} |"
    )
    lines.append(
        f"| Equal-weight selected wallets | {format_pct(full_equal.total_return)} | {format_pct(full_equal.cagr)} | {full_equal.sharpe:.2f} | {format_pct(full_equal.max_drawdown)} | {full_equal.trades} | {format_pct(full_equal.win_rate)} | {format_pct(full_equal.exposure)} |"
    )
    lines.append(
        f"| Buy & hold BTC (no costs) | {format_pct(full_buy_hold.total_return)} | {format_pct(full_buy_hold.cagr)} | {full_buy_hold.sharpe:.2f} | {format_pct(full_buy_hold.max_drawdown)} | {full_buy_hold.trades} | {format_pct(full_buy_hold.win_rate)} | {format_pct(full_buy_hold.exposure)} |"
    )

    lines.append("")
    lines.append("### Out-of-sample period (last 30%)")
    lines.append("| Strategy | Total Return | CAGR | Sharpe | Max Drawdown | Trades | Win Rate | Exposure |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| Weighted smart-wallet consensus | {format_pct(oos_weighted.total_return)} | {format_pct(oos_weighted.cagr)} | {oos_weighted.sharpe:.2f} | {format_pct(oos_weighted.max_drawdown)} | {oos_weighted.trades} | {format_pct(oos_weighted.win_rate)} | {format_pct(oos_weighted.exposure)} |"
    )
    lines.append(
        f"| Equal-weight selected wallets | {format_pct(oos_equal.total_return)} | {format_pct(oos_equal.cagr)} | {oos_equal.sharpe:.2f} | {format_pct(oos_equal.max_drawdown)} | {oos_equal.trades} | {format_pct(oos_equal.win_rate)} | {format_pct(oos_equal.exposure)} |"
    )
    lines.append(
        f"| Buy & hold BTC (no costs) | {format_pct(oos_bh.total_return)} | {format_pct(oos_bh.cagr)} | {oos_bh.sharpe:.2f} | {format_pct(oos_bh.max_drawdown)} | {oos_bh.trades} | {format_pct(oos_bh.win_rate)} | {format_pct(oos_bh.exposure)} |"
    )

    lines.append("")
    lines.append("## 5) Interpretation")
    lines.append("- The weighted strategy emphasizes wallets with better in-sample risk-adjusted copy-trading performance and more active BTC participation.")
    lines.append("- Comparing weighted vs equal-weight reveals whether wallet-quality weighting adds value beyond simple diversification.")
    lines.append("- Out-of-sample metrics are the primary validity check; if they degrade materially, re-estimate weights more conservatively and reduce turnover.")
    lines.append("- This is a research backtest only and excludes slippage, latency, and market impact from following public flow.")

    output.write_text("\n".join(lines) + "\n")


def main() -> None:
    btc = read_btc_data(BTC_CSV)
    times = btc["time"]
    closes = btc["close"]
    wallet_flow = read_wallet_btc_hourly_flow(HYPER_CSV)

    overlap_start = min(min(flows.keys()) for flows in wallet_flow.values() if flows)
    start_idx = next(i for i, ts in enumerate(times) if ts >= overlap_start)

    times = times[start_idx:]
    closes = closes[start_idx:]

    train_end_idx = int(len(times) * TRAIN_RATIO)
    selected = select_wallets(wallet_flow, times, closes, train_end_idx)
    threshold = 0.20

    write_report(OUTPUT_MD, times, closes, selected, threshold, train_end_idx, wallet_flow)
    print(f"Report written to {OUTPUT_MD}")


if __name__ == "__main__":
    main()
