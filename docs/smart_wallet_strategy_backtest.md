# Smart Wallet BTC Strategy & Backtest

## 1) Data and objective
- BTC hourly candles from `data/btcusdt_1h_history.csv`; sample analyzed: **2025-06-29T16:00:00+00:00 to 2026-02-15T16:00:00+00:00** (5545 bars).
- Smart-wallet trades from `data/hyperliquid_position_history.csv` (BTC fills only, aggregated to hourly net signed notional).
- Goal: rank wallets by in-sample predictive quality, then follow a weighted consensus signal.

## 2) Methodology
1. Convert each wallet's hourly BTC flow into a direction signal: buy=+1, sell=-1, no trade=0.
2. Use the first 70% of the overlapping sample as **training**, remaining 30% as **out-of-sample test**.
3. For each wallet, compute in-sample performance when naively copying that wallet with one-bar delay and 5 bps one-way cost.
4. Wallet score = `max(hit_rate - 50%, 0) * sqrt(active_hours)`; select top wallets with positive score.
5. Build portfolio consensus score per hour: weighted sum of selected wallet directions.
6. Trading rule: long if consensus > 0.20, short if consensus < -0.20, else flat.

## 3) Selected smart wallets and weights

| Wallet | Train Active Hours | Train Hit Rate | Train Sharpe | Train Return | Portfolio Weight |
|---|---:|---:|---:|---:|---:|
| `0xcdc784389ce6f038a653c29b7c92248a17f5b60a` | 12 | 75.00% | 0.74 | 1.30% | 77.36% |
| `0x01df303b2369290d1aec6fe37c1a3cd4a0c962ca` | 13 | 53.85% | -0.60 | -0.40% | 12.39% |
| `0xf1ed8db37b7474fb5bfe01b58def6001955a2d2a` | 19 | 52.63% | 0.33 | 0.80% | 10.25% |

## 4) Backtest results

### Full period
| Strategy | Total Return | CAGR | Sharpe | Max Drawdown | Trades | Win Rate | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| Weighted smart-wallet consensus | -10.66% | -16.32% | -2.30 | -12.50% | 36 | 33.33% | 0.96% |
| Equal-weight selected wallets | -7.42% | -11.46% | -1.04 | -12.07% | 64 | 40.62% | 1.64% |
| Buy & hold BTC (no costs) | -35.80% | -50.35% | -1.46 | -50.08% | 1 | 0.00% | 99.98% |

### Out-of-sample period (last 30%)
| Strategy | Total Return | CAGR | Sharpe | Max Drawdown | Trades | Win Rate | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| Weighted smart-wallet consensus | -11.77% | -48.26% | -5.22 | -11.77% | 27 | 18.52% | 2.46% |
| Equal-weight selected wallets | -8.92% | -38.85% | -2.84 | -11.33% | 29 | 24.14% | 2.82% |
| Buy & hold BTC (no costs) | -24.81% | -77.72% | -2.84 | -35.58% | 1 | 0.00% | 99.94% |

## 5) Interpretation
- The weighted strategy emphasizes wallets with better in-sample risk-adjusted copy-trading performance and more active BTC participation.
- Comparing weighted vs equal-weight reveals whether wallet-quality weighting adds value beyond simple diversification.
- Out-of-sample metrics are the primary validity check; if they degrade materially, re-estimate weights more conservatively and reduce turnover.
- This is a research backtest only and excludes slippage, latency, and market impact from following public flow.
