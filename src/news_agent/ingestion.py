from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from collections.abc import Callable, Sequence
import json
import os
from urllib.parse import quote_plus, urlencode

from .hyperliquid import HyperliquidInfoClient, HyperliquidPosition, HyperliquidTrade, WalletPerformance, aggregate_trade_history, normalize_positions
from .live_sources import FeedEntry, fetch_text, parse_feed_entries
from .models import Event, UserProfile, utcnow
from .normalization import extract_entities, normalize_event, parse_timestamp

DEFAULT_NEWS_FEEDS = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
)

REDDIT_SEARCH_FEED = "https://www.reddit.com/search.rss?q={query}&sort=new&t=day"
ETHERSCAN_TX_URL = "https://api.etherscan.io/api"

NEWS_SOURCE_CREDIBILITY = {
    "coindesk.com": 0.84,
    "cointelegraph.com": 0.78,
    "decrypt.co": 0.75,
}

SOCIAL_SOURCE_CREDIBILITY = {
    "reddit.com": 0.52,
    "www.reddit.com": 0.52,
}

HYPERLIQUID_SOURCE_CREDIBILITY = 0.9

IMPACT_KEYWORDS = {
    "etf": 0.18,
    "approval": 0.12,
    "sec": 0.12,
    "hack": 0.2,
    "exploit": 0.2,
    "lawsuit": 0.14,
    "liquidation": 0.12,
    "whale": 0.11,
    "inflow": 0.1,
    "outflow": 0.1,
    "listing": 0.08,
    "delist": 0.12,
}

POSITIVE_SENTIMENT_TERMS = {
    "approval",
    "rally",
    "surge",
    "breakout",
    "partnership",
    "launch",
    "adoption",
}

NEGATIVE_SENTIMENT_TERMS = {
    "hack",
    "exploit",
    "lawsuit",
    "ban",
    "liquidation",
    "breach",
    "fraud",
    "outflow",
}

TextGetter = Callable[[str], str]


class BaseIngestor:
    source_type: str

    def ingest(self, payloads: Iterable[dict]) -> list[Event]:
        events: list[Event] = []
        for payload in payloads:
            try:
                events.append(normalize_event(self.source_type, payload))
            except (TypeError, ValueError):
                continue
        return events

    def fetch_latest(self, user_profile: UserProfile, limit: int = 25) -> list[dict]:
        return []


class OnChainIngestor(BaseIngestor):
    source_type = "onchain"

    def __init__(self, http_get: TextGetter = fetch_text) -> None:
        self.http_get = http_get

    def fetch_latest(self, user_profile: UserProfile, limit: int = 25) -> list[dict]:
        api_key = os.getenv("ETHERSCAN_API_KEY", "").strip()
        wallets = _wallets_for_profile(user_profile)
        if not api_key or not wallets:
            return []

        payloads: list[dict] = []
        per_wallet_limit = max(1, min(10, max(limit, 1)))
        for wallet in wallets:
            params = urlencode(
                {
                    "module": "account",
                    "action": "txlist",
                    "address": wallet,
                    "sort": "desc",
                    "offset": per_wallet_limit,
                    "page": 1,
                    "apikey": api_key,
                }
            )
            url = f"{ETHERSCAN_TX_URL}?{params}"
            try:
                raw = self.http_get(url)
                response = json.loads(raw)
            except (OSError, ValueError):
                continue

            result = response.get("result", [])
            if not isinstance(result, list):
                continue

            for tx in result:
                payload = _tx_to_payload(wallet, tx)
                if payload:
                    payloads.append(payload)

        payloads.sort(key=lambda p: _sort_timestamp(p.get("timestamp")), reverse=True)
        return payloads[: max(limit, 0)]


class NewsIngestor(BaseIngestor):
    source_type = "news"

    def __init__(self, feed_urls: Sequence[str] | None = None, http_get: TextGetter = fetch_text) -> None:
        self.feed_urls = list(feed_urls or DEFAULT_NEWS_FEEDS)
        self.http_get = http_get

    def fetch_latest(self, user_profile: UserProfile, limit: int = 25) -> list[dict]:
        entries: list[FeedEntry] = []
        for feed_url in self._configured_feeds():
            try:
                xml_text = self.http_get(feed_url)
            except OSError:
                continue
            entries.extend(parse_feed_entries(xml_text, feed_url))

        if not entries:
            return []

        token_mentions = _token_mentions(entries, user_profile.token_watchlist)
        peak_mentions = max(token_mentions.values(), default=1)
        now_iso = utcnow().isoformat()

        payloads: list[dict] = []
        for entry in entries:
            text = f"{entry.title} {entry.summary}".strip()
            entities = extract_entities(text)
            watched_entities = [entity for entity in entities if entity in user_profile.token_watchlist]
            mention_score = max((token_mentions[e] for e in watched_entities), default=0)
            spike_ratio = mention_score / peak_mentions if mention_score else 0.0

            payloads.append(
                {
                    "timestamp": entry.published or now_iso,
                    "title": entry.title,
                    "summary": entry.title,
                    "entities": entities,
                    "sentiment_score": _sentiment_from_text(text),
                    "magnitude_score": _magnitude_from_text(text, base=0.5),
                    "source_credibility": _news_source_credibility(entry.source),
                    "engagement_score": _clamp(0.45 + (spike_ratio * 0.45)),
                    "velocity_change": _clamp(0.35 + (spike_ratio * 0.65)),
                    "source_links": [entry.link] if entry.link else [],
                }
            )

        payloads.sort(key=lambda p: _sort_timestamp(p.get("timestamp")), reverse=True)
        return payloads[: max(limit, 0)]

    def _configured_feeds(self) -> list[str]:
        env_feeds = _split_csv(os.getenv("NEWS_AGENT_NEWS_FEEDS"))
        if env_feeds:
            return env_feeds
        return self.feed_urls


class SocialIngestor(BaseIngestor):
    source_type = "social"

    def __init__(
        self,
        search_template: str = REDDIT_SEARCH_FEED,
        http_get: TextGetter = fetch_text,
    ) -> None:
        self.search_template = search_template
        self.http_get = http_get

    def fetch_latest(self, user_profile: UserProfile, limit: int = 25) -> list[dict]:
        tracked_terms = _social_terms(user_profile)
        if not tracked_terms:
            return []

        entries_by_term: list[tuple[str, FeedEntry]] = []
        for term in tracked_terms:
            query = quote_plus(f"{term} crypto")
            feed_url = self.search_template.format(query=query)
            try:
                xml_text = self.http_get(feed_url)
            except OSError:
                continue

            for entry in parse_feed_entries(xml_text, feed_url):
                entries_by_term.append((term, entry))

        if not entries_by_term:
            return []

        term_counts = Counter(term for term, _ in entries_by_term)
        peak_term_count = max(term_counts.values(), default=1)
        now_iso = utcnow().isoformat()

        payloads: list[dict] = []
        for term, entry in entries_by_term:
            text = f"{entry.title} {entry.summary}".strip()
            term_ratio = term_counts[term] / peak_term_count
            payloads.append(
                {
                    "timestamp": entry.published or now_iso,
                    "text": entry.title,
                    "summary": entry.title,
                    "entities": extract_entities(text),
                    "sentiment_score": _sentiment_from_text(text),
                    "magnitude_score": _magnitude_from_text(text, base=0.4 + (term_ratio * 0.2)),
                    "source_credibility": SOCIAL_SOURCE_CREDIBILITY.get(entry.source, 0.5),
                    "engagement_score": _clamp(0.4 + (term_ratio * 0.5)),
                    "velocity_change": _clamp(0.45 + (term_ratio * 0.55)),
                    "source_links": [entry.link] if entry.link else [],
                }
            )

        payloads.sort(key=lambda p: _sort_timestamp(p.get("timestamp")), reverse=True)
        return payloads[: max(limit, 0)]


class HyperliquidIngestor(BaseIngestor):
    source_type = "hyperliquid"

    def __init__(self, client: HyperliquidInfoClient | None = None) -> None:
        info_url = os.getenv("HYPERLIQUID_INFO_URL", "").strip()
        if client is not None:
            self.client = client
        elif info_url:
            self.client = HyperliquidInfoClient(info_url=info_url)
        else:
            self.client = HyperliquidInfoClient()

    def fetch_latest(self, user_profile: UserProfile, limit: int = 25) -> list[dict]:
        wallets = _hyperliquid_wallets_for_profile(user_profile)
        if not wallets:
            return []

        payloads: list[dict] = []
        per_wallet_fill_limit = max(5, min(250, max(limit, 1) * 4))
        per_wallet_trade_events = max(2, min(20, limit // max(len(wallets), 1)))

        for wallet in wallets:
            fills = self.client.user_fills(wallet, limit=per_wallet_fill_limit)
            state = self.client.clearinghouse_state(wallet)
            positions = normalize_positions(wallet, state)
            trades, performance = aggregate_trade_history(wallet, fills)

            open_orders = self.client.frontend_open_orders(wallet)
            if not open_orders:
                open_orders = self.client.open_orders(wallet)
            open_order_count = len(open_orders)

            payloads.extend(_hyperliquid_position_payloads(positions, open_order_count))
            payloads.extend(_hyperliquid_trade_payloads(trades, per_wallet_trade_events))

            summary_payload = _hyperliquid_performance_payload(performance, positions, open_order_count)
            if summary_payload:
                payloads.append(summary_payload)

        payloads.sort(key=lambda p: _sort_timestamp(p.get("timestamp")), reverse=True)
        return payloads[: max(limit, 0)]


def _wallets_for_profile(user_profile: UserProfile) -> list[str]:
    env_wallets = _split_csv(os.getenv("NEWS_AGENT_WHALE_WALLETS"))
    if env_wallets:
        return env_wallets
    return sorted(user_profile.whale_wallets)


def _hyperliquid_wallets_for_profile(user_profile: UserProfile) -> list[str]:
    env_wallets = _split_csv(os.getenv("NEWS_AGENT_HYPERLIQUID_WALLETS"))
    if env_wallets:
        return env_wallets
    configured = sorted(user_profile.hyperliquid_wallets)
    if configured:
        return configured
    return sorted(user_profile.whale_wallets)


def _social_terms(user_profile: UserProfile) -> list[str]:
    env_terms = _split_csv(os.getenv("NEWS_AGENT_SOCIAL_TERMS"))
    if env_terms:
        terms = env_terms
    else:
        terms = sorted(user_profile.token_watchlist)

    max_terms_raw = os.getenv("NEWS_AGENT_SOCIAL_MAX_TERMS", "5")
    try:
        max_terms = max(1, int(max_terms_raw))
    except ValueError:
        max_terms = 5
    return terms[:max_terms]


def _token_mentions(entries: list[FeedEntry], watchlist: set[str]) -> Counter[str]:
    mentions: Counter[str] = Counter()
    tracked = {token.upper() for token in watchlist}
    if not tracked:
        return mentions

    for entry in entries:
        text = f"{entry.title} {entry.summary}".upper()
        for token in tracked:
            if token in text:
                mentions[token] += 1
    return mentions


def _tx_to_payload(wallet: str, tx: dict) -> dict | None:
    value_wei = _safe_int(tx.get("value"))
    if value_wei <= 0:
        return None

    wallet_lower = wallet.lower()
    from_address = str(tx.get("from", ""))
    to_address = str(tx.get("to", ""))
    tx_hash = str(tx.get("hash", ""))
    direction = "outflow" if from_address.lower() == wallet_lower else "inflow"
    value_eth = value_wei / 1_000_000_000_000_000_000
    short_wallet = f"{wallet[:6]}...{wallet[-4:]}" if len(wallet) > 10 else wallet
    short_counterparty = f"{to_address[:6]}...{to_address[-4:]}" if len(to_address) > 10 else to_address

    summary = f"Tracked wallet {short_wallet} {direction} {value_eth:.2f} ETH"
    if short_counterparty:
        summary += f" to {short_counterparty}"

    velocity_bonus = min(value_eth / 1_000, 0.4)
    magnitude_bonus = min(value_eth / 500, 0.65)
    entities = [entity for entity in [wallet, from_address, to_address, "ETH"] if entity]

    payload = {
        "timestamp": tx.get("timeStamp"),
        "summary": summary,
        "entities": entities,
        "sentiment_score": 0.0,
        "magnitude_score": _clamp(0.35 + magnitude_bonus),
        "source_credibility": 0.92,
        "engagement_score": 0.65,
        "velocity_change": _clamp(0.45 + velocity_bonus),
        "source_links": [f"https://etherscan.io/tx/{tx_hash}"] if tx_hash else [],
    }
    return payload


def _hyperliquid_position_payloads(positions: list[HyperliquidPosition], open_order_count: int) -> list[dict]:
    payloads: list[dict] = []
    for position in positions:
        sentiment = 0.2 if position.unrealized_pnl > 0 else -0.2 if position.unrealized_pnl < 0 else 0.0
        payloads.append(
            {
                "timestamp": position.last_updated.isoformat(),
                "summary": (
                    f"Hyperliquid {_short_wallet(position.wallet)} {position.symbol} {position.side} "
                    f"{position.size:.4f} @ {position.entry_price:.2f}, uPnL {position.unrealized_pnl:+.2f}"
                ),
                "entities": [position.wallet, position.symbol, "HYPERLIQUID"],
                "sentiment_score": sentiment,
                "magnitude_score": _hyperliquid_magnitude(abs(position.unrealized_pnl), position.size),
                "source_credibility": HYPERLIQUID_SOURCE_CREDIBILITY,
                "engagement_score": _clamp(0.55 + min(open_order_count, 10) * 0.03),
                "velocity_change": _clamp(0.5 + min(open_order_count, 8) * 0.04),
                "source_links": [f"https://app.hyperliquid.xyz/trader/{position.wallet}"],
                "event_type": "position_snapshot",
                "entry_price": position.entry_price,
                "mark_price": position.mark_price,
                "unrealized_pnl": position.unrealized_pnl,
                "wallet": position.wallet,
            }
        )
    return payloads


def _hyperliquid_trade_payloads(trades: list[HyperliquidTrade], limit: int) -> list[dict]:
    if not trades:
        return []

    selected = sorted(trades, key=lambda trade: trade.timestamp, reverse=True)[: max(limit, 0)]
    payloads: list[dict] = []
    for trade in selected:
        sentiment = 0.25 if trade.realized_pnl > 0 else -0.25 if trade.realized_pnl < 0 else 0.0
        summary = (
            f"Hyperliquid {_short_wallet(trade.wallet)} {trade.symbol} {trade.side} "
            f"{trade.size:.4f} @ {trade.price:.2f}, rPnL {trade.realized_pnl:+.2f}"
        )
        payloads.append(
            {
                "timestamp": trade.timestamp.isoformat(),
                "summary": summary,
                "entities": [trade.wallet, trade.symbol, "HYPERLIQUID"],
                "sentiment_score": sentiment,
                "magnitude_score": _hyperliquid_magnitude(abs(trade.realized_pnl), trade.size),
                "source_credibility": HYPERLIQUID_SOURCE_CREDIBILITY,
                "engagement_score": 0.7,
                "velocity_change": 0.75,
                "source_links": [f"https://app.hyperliquid.xyz/trader/{trade.wallet}"],
                "event_type": "fill",
                "trade_id": trade.trade_id,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "realized_pnl": trade.realized_pnl,
                "cumulative_wallet_pnl": trade.cumulative_pnl,
                "wallet": trade.wallet,
            }
        )
    return payloads


def _hyperliquid_performance_payload(
    performance: WalletPerformance,
    positions: list[HyperliquidPosition],
    open_order_count: int,
) -> dict | None:
    if performance.trade_count == 0 and not positions:
        return None

    unrealized_total = sum(position.unrealized_pnl for position in positions)
    realized_total = performance.total_realized_pnl
    combined_abs_pnl = abs(realized_total) + abs(unrealized_total)
    symbols = sorted({position.symbol for position in positions}) or ["HYPERLIQUID"]

    sentiment = 0.2 if realized_total + unrealized_total > 0 else -0.2 if realized_total + unrealized_total < 0 else 0.0
    return {
        "timestamp": performance.latest_trade_time.isoformat(),
        "summary": (
            f"Hyperliquid {_short_wallet(performance.wallet)} performance: "
            f"fills={performance.trade_count}, realized={realized_total:+.2f}, "
            f"unrealized={unrealized_total:+.2f}, win_rate={performance.win_rate:.0%}"
        ),
        "entities": [performance.wallet, *symbols],
        "sentiment_score": sentiment,
        "magnitude_score": _hyperliquid_magnitude(combined_abs_pnl, max(len(positions), 1)),
        "source_credibility": HYPERLIQUID_SOURCE_CREDIBILITY,
        "engagement_score": _clamp(0.55 + min(open_order_count, 10) * 0.03),
        "velocity_change": _clamp(0.45 + min(performance.trade_count, 20) * 0.02),
        "source_links": [f"https://app.hyperliquid.xyz/trader/{performance.wallet}"],
        "event_type": "wallet_performance",
        "wallet": performance.wallet,
        "trade_count": performance.trade_count,
        "total_realized_pnl": realized_total,
        "total_unrealized_pnl": unrealized_total,
        "cumulative_fees": performance.cumulative_fees,
    }


def _safe_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _short_wallet(wallet: str) -> str:
    if len(wallet) <= 12:
        return wallet
    return f"{wallet[:6]}...{wallet[-4:]}"


def _hyperliquid_magnitude(abs_pnl: float, size: float) -> float:
    pnl_component = min(abs_pnl / 10_000, 1.0) * 0.55
    size_component = min(size / 5, 1.0) * 0.25
    return _clamp(0.35 + pnl_component + size_component)


def _sort_timestamp(value: object) -> object:
    try:
        return parse_timestamp(value)
    except (TypeError, ValueError):
        return utcnow()


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _news_source_credibility(source: str) -> float:
    if not source:
        return 0.68
    for domain, score in NEWS_SOURCE_CREDIBILITY.items():
        if domain in source:
            return score
    return 0.68


def _magnitude_from_text(text: str, base: float) -> float:
    lowered = text.lower()
    score = base
    for keyword, weight in IMPACT_KEYWORDS.items():
        if keyword in lowered:
            score += weight
    return _clamp(score)


def _sentiment_from_text(text: str) -> float:
    lowered = text.lower()
    positive_hits = sum(1 for term in POSITIVE_SENTIMENT_TERMS if term in lowered)
    negative_hits = sum(1 for term in NEGATIVE_SENTIMENT_TERMS if term in lowered)
    if positive_hits == negative_hits:
        return 0.0
    delta = positive_hits - negative_hits
    return max(-1.0, min(1.0, delta / 3))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
