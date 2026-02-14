# News Agent (Crypto-First MVP)

Python implementation of the Phase 1 core from the **Vibe Coding Development Plan**:

- Live data ingestion (on-chain/news/social)
- Event normalization into a unified event object
- Deterministic actionability scoring
- Lightweight personalization feedback model
- Alert engine with confidence + reasoning context

## Run (Live Mode)

`live` is now the default mode. It fetches:

- News from crypto RSS feeds
- Social signals from Reddit search RSS (watchlist-driven)
- On-chain transfers from Etherscan (when `ETHERSCAN_API_KEY` is set)

```bash
PYTHONPATH=src python -m news_agent.cli --mode live
```

Force live-only (no demo fallback):

```bash
PYTHONPATH=src python -m news_agent.cli --mode live --strict-live
```

## Demo Mode

```bash
PYTHONPATH=src python -m news_agent.cli --mode demo
```

## Config (Environment Variables)

- `NEWS_AGENT_WATCHLIST` (default: `BTC,ETH,SOL`)
- `NEWS_AGENT_WHALE_WALLETS` (comma-separated wallet addresses)
- `NEWS_AGENT_ALERT_THRESHOLD` (default: `0.55`)
- `NEWS_AGENT_FETCH_LIMIT` (default: `25`)
- `NEWS_AGENT_NEWS_FEEDS` (comma-separated RSS URLs)
- `NEWS_AGENT_SOCIAL_TERMS` (comma-separated terms for social ingestion)
- `NEWS_AGENT_SOCIAL_MAX_TERMS` (default: `5`)
- `ETHERSCAN_API_KEY` (required for live on-chain ingestion)

Example:

```bash
export NEWS_AGENT_WATCHLIST="BTC,ETH,SOL,ARB"
export NEWS_AGENT_ALERT_THRESHOLD="0.5"
export ETHERSCAN_API_KEY="your_key_here"
PYTHONPATH=src python -m news_agent.cli --mode live
```

## Test

```bash
PYTHONPATH=src pytest
```
