# Trading Strategies Report

## Data used
- BTCUSDT 1h candles: `data/btcusdt_1h_history.csv` (74381 rows, 2017-08-17T04:00:00+00:00 to 2026-02-15T16:00:00+00:00).
- Hyperliquid position/fill history: `data/hyperliquid_position_history.csv` (used for BTC flow feature).
- Backtest assumptions: one-bar signal delay, 0.05% transaction cost per unit turnover.

## Benchmark (buy-and-hold BTC, no costs)
- Total return: **1502.48%**, CAGR: **38.64%**, Sharpe: **0.81**, Max drawdown: **-83.91%**.

## Strategy ideas and backtest results

| Rank | Strategy | Total Return | CAGR | Sharpe | Max DD | Trades | Win Rate | Exposure |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | SMA 50/200 Trend | -9.41% | -1.16% | 0.35 | -74.12% | 491 | 32.99% | 99.73% |
| 2 | Taker Imbalance Momentum | -59.54% | -10.11% | -0.46 | -60.30% | 377 | 37.67% | 3.02% |
| 3 | Hyperliquid Flow Momentum | -12.78% | -1.60% | -0.54 | -17.13% | 112 | 38.39% | 0.18% |
| 4 | RSI Mean Reversion | -91.71% | -25.42% | -0.70 | -98.50% | 2235 | 64.34% | 11.01% |
| 5 | 20h Breakout + Volume | -98.59% | -39.44% | -1.95 | -98.67% | 3254 | 34.57% | 5.59% |

## Strategy notes
- **SMA 50/200 Trend**: Long when SMA(50) > SMA(200), short otherwise.
- **Taker Imbalance Momentum**: Trade with 12-hour average taker buy/sell imbalance on Binance spot candles.
- **Hyperliquid Flow Momentum**: Use hourly BTC net notional flow z-score from Hyperliquid fills; trade in flow direction when |z| > 1.
- **RSI Mean Reversion**: Long when RSI(14) < 30, short when RSI(14) > 70, flat in between.
- **20h Breakout + Volume**: Enter on 20-hour breakout only when volume is 1.5x above 20-hour average.

## Interpretation
- Best risk-adjusted performer in this run is **SMA 50/200 Trend** with Sharpe **0.35** and max drawdown **-74.12%**.
- Results are sensitive to fee/slippage assumptions and should be treated as research prototypes, not production trading advice.
- Next steps: walk-forward validation, parameter sweep with out-of-sample splits, and instrumenting market-impact-aware execution.
