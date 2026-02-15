# 📊 Hyperliquid On-Chain Trading Data Collection Plan

## 🧠 Objective

Capture detailed **spot & perpetual trading position data** for selected Hyperliquid traders, including:

* **Open & closed positions**
* **Entry price**
* **Exit price**
* **Realized and unrealized PnL**
* Per‐trade fills
* Wallet performance history

This data will feed analytics platforms, dashboards, or automated strategies.

---

## 🧱 Architecture Overview

```
+---------------------+
|   Data Consumers    |
| (Analytics/UIs/AI)  |
+----------▲----------+
           |
   +-------|-------+
   |  Storage / ETL |
   +-------|--------+
           |
   +-------v-------+
   | Data Fetchers |
   +-------|--------+
           |
+----------|----------+
| REST APIs & WS Feeds|
|  Hyperliquid +      |
|  Indexers (Nansen / |
|  HyData / Zerion)   |
+---------------------+
```

---

## 📡 Data Sources

### 🔹 Official Hyperliquid API

* **Info Endpoint** (REST) — includes user fills and account state.([hyperliquid.gitbook.io][1])
  Example query types:

  * `userFills`: most recent fills for a user
  * `openOrders` / `frontendOpenOrders`: active orders
  * (future): funding, balances

This will provide granular trade execution data.

> Note: exchange endpoints are for trading actions and require signatures — not needed for passive data collection.([hyperliquid.gitbook.io][2])

---

### 🔹 Third-Party Indexer APIs

These are crucial because:

* Official API has limited historical position endpoints
* Indexers already transform on-chain data into usable responses

**Examples (optional integration layers)**:

| Provider                   | What to Use                                                          |                       |
| -------------------------- | -------------------------------------------------------------------- | --------------------- |
| **Nansen Hyperliquid API** | Detailed perp positions & trades history (entry/exit/PnL) per wallet | ([docs.nansen.ai][3]) |
| **HyData API**             | Wallet analytics, transfer classification, recent trades             | ([hydata.dev][4])     |
| **Moon Dev API**           | Current positions and fills per wallet                               | ([Moon Dev][5])       |
| **Zerion API**             | Cross-chain positions & PnL                                          | ([zerion.io][6])      |

> Use indexers *especially* for historical positions and time-series PnL that the official API alone doesn’t provide efficiently.

---

## 📌 Key Concepts & Calculations

### 💡 Entry / Exit Price & PnL Logic

Hyperliquid’s entry price and PnL are *frontend calculations* built on underlying position basis and fills.([hyperliquid.gitbook.io][7])

* **Perpetual Entry Price**
  Weighted average of trades that increased position size.

* **Unrealized PnL**
  `side * (mark_price − entry_price) * position_size`

* **Closed (Realized) PnL**
  Includes fees and price difference on exits.([hyperliquid.gitbook.io][7])

Use API fill records + positions state to reconstruct these metrics if a direct field isn’t available.

---

## 📍 Data Collection Modules

### 🛠️ 1. Wallet Tracker

Tracks a list of target traders (addresses):

* Input: wallet addresses
* Output: latest open positions (perp + spot)
* Refresh interval: 1–10 min / WS

Data points:

* Position size & side
* Entry price (derived)
* Mark price
* Unrealized PnL

**Sources:**

* Nansen / Moon Dev `/positions`
* Official fills to calibrate real PnL

---

### 🛠️ 2. Trade History & PnL Aggregator

Goal: build complete trade timeline per wallet.

Steps:

1. Fetch **fills**

   * from official API’s `userFills`
   * or indexer trade history (`/perp-trades` from Nansen)

2. Normalize:

   * timestamp
   * trading pair
   * side, size, price
   * fee

3. Compute:

   * entry vs exit sequences
   * per-trade realized PnL
   * cumulative wallet PnL

**Use cases:**

* Trade reconciliation
* Profit leaderboard
* Strategy performance

---

### 🛠️ 3. Real-Time Stream Processor (Optional but Valuable)

Keep short latency views of positions:

* Connect to WebSocket feeds (if available) for user updates
* Process new fills in real time
* Update position state & PnL

---

## 🗃 Storage Schema & Design

### 🔹 `positions`

| Field          | Type      | Description    |
| -------------- | --------- | -------------- |
| wallet         | string    | Address        |
| symbol         | string    | BTC/ETH        |
| side           | enum      | long/short     |
| size           | float     | Position size  |
| entry_price    | float     | Weighted entry |
| mark_price     | float     | Current mark   |
| unrealized_pnl | float     | Live           |
| last_updated   | timestamp | Timestamp      |

---

### 🔹 `trades`

| Field        | Type     | Description |
| ------------ | -------- | ----------- |
| wallet       | string   | Address     |
| trade_id     | string   | Provider ID |
| symbol       | string   | BTC/USDC    |
| side         | enum     | buy/sell    |
| size         | float    |             |
| price        | float    |             |
| fee          | float    |             |
| timestamp    | datetime |             |
| realized_pnl | float    | Derived     |

---

## 🧪 Validation & Benchmarks

* Cross-validate PnL vs official wallet history (UI feeds)
* Reconcile entry prices against weighted fill averages
* Replay historical trades to verify exit detection

---

## 🚀 Next Steps

1. **Define trader selection criteria**

   * wallets by volume / profitability / leaderboard

2. **Wire up API credentials** for indexers

3. **Build offline ETLs** to backfill months of data

4. **Deploy streaming updaters** if real-time usage is required

---

## 📌 Notes & Tips

* Direct entry/exit fields might not exist in all APIs — *reconstruct* them from fills + positions.([hyperliquid.gitbook.io][7])
* Use indexers when possible — they offer enriched datasets.([docs.nansen.ai][3])
* Be mindful of pagination limits on official endpoints — plan roll-ups.
