from news_agent.ingestion import NewsIngestor, SocialIngestor
from news_agent.models import UserProfile

SAMPLE_RSS = """\
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>SEC approves spot BTC ETF</title>
      <description>Major regulatory update for Bitcoin.</description>
      <link>https://example.com/news/btc-etf</link>
      <pubDate>Fri, 14 Feb 2026 09:15:00 GMT</pubDate>
    </item>
    <item>
      <title>ETH developer update ships</title>
      <description>Protocol improvements continue.</description>
      <link>https://example.com/news/eth-dev</link>
      <pubDate>Fri, 14 Feb 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_news_ingestor_fetches_rss_payloads(monkeypatch) -> None:
    monkeypatch.delenv("NEWS_AGENT_NEWS_FEEDS", raising=False)
    ingestor = NewsIngestor(feed_urls=["https://example.com/feed"], http_get=lambda _: SAMPLE_RSS)
    user = UserProfile(token_watchlist={"BTC", "ETH"}, whale_wallets=set(), alert_threshold=0.5)

    payloads = ingestor.fetch_latest(user, limit=10)

    assert len(payloads) == 2
    assert payloads[0]["summary"] == "SEC approves spot BTC ETF"
    assert payloads[0]["source_links"] == ["https://example.com/news/btc-etf"]
    assert payloads[0]["magnitude_score"] >= payloads[1]["magnitude_score"]


def test_social_ingestor_uses_watchlist_queries(monkeypatch) -> None:
    monkeypatch.delenv("NEWS_AGENT_SOCIAL_TERMS", raising=False)
    monkeypatch.setenv("NEWS_AGENT_SOCIAL_MAX_TERMS", "1")
    ingestor = SocialIngestor(http_get=lambda _: SAMPLE_RSS, search_template="https://example.com?q={query}")
    user = UserProfile(token_watchlist={"BTC", "ETH"}, whale_wallets=set(), alert_threshold=0.5)

    payloads = ingestor.fetch_latest(user, limit=5)

    assert payloads
    assert payloads[0]["source_links"]
    assert payloads[0]["source_credibility"] > 0
