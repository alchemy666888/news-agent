from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from collections.abc import Callable, Sequence
import json
import os
from urllib.parse import quote_plus, urlencode

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


def _wallets_for_profile(user_profile: UserProfile) -> list[str]:
    env_wallets = _split_csv(os.getenv("NEWS_AGENT_WHALE_WALLETS"))
    if env_wallets:
        return env_wallets
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


def _safe_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


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
