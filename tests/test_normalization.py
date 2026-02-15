from datetime import timezone

from news_agent.normalization import parse_timestamp


def test_parse_timestamp_supports_rfc2822() -> None:
    ts = parse_timestamp("Fri, 14 Feb 2026 09:15:00 GMT")
    assert ts.year == 2026
    assert ts.month == 2
    assert ts.day == 14
    assert ts.tzinfo == timezone.utc


def test_parse_timestamp_supports_unix_string() -> None:
    ts = parse_timestamp("1739520000")
    assert ts.year == 2025
    assert ts.month == 2


def test_parse_timestamp_supports_millisecond_epoch() -> None:
    ts = parse_timestamp(1739520000000)
    assert ts.year == 2025
    assert ts.month == 2
