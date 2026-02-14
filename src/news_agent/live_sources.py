from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

DEFAULT_USER_AGENT = "news-agent/0.1 (+https://example.com/news-agent)"
DEFAULT_TIMEOUT_SECONDS = 12.0


@dataclass(slots=True)
class FeedEntry:
    title: str
    summary: str
    link: str
    published: str
    source: str


def fetch_text(url: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
    return payload.decode(encoding, errors="replace")


def parse_feed_entries(xml_text: str, fallback_source_url: str) -> list[FeedEntry]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    root_name = _tag_name(root.tag)
    if root_name == "rss":
        return _parse_rss(root, fallback_source_url)
    if root_name == "feed":
        return _parse_atom(root, fallback_source_url)
    return []


def _parse_rss(root: ET.Element, fallback_source_url: str) -> list[FeedEntry]:
    channel = _find_child(root, "channel")
    if channel is None:
        return []

    entries: list[FeedEntry] = []
    for item in _iter_children(channel, "item"):
        title = _clean_text(_find_text(item, "title"))
        summary = _clean_text(_find_text(item, "description", "summary", "encoded"))
        link = _find_text(item, "link")
        published = _find_text(item, "pubDate", "date", "published", "updated")
        source = _extract_host(link) or _extract_host(fallback_source_url)

        if not title and not summary:
            continue
        if not title:
            title = summary[:180]
        if not summary:
            summary = title

        entries.append(
            FeedEntry(
                title=title,
                summary=summary,
                link=link,
                published=published,
                source=source,
            )
        )
    return entries


def _parse_atom(root: ET.Element, fallback_source_url: str) -> list[FeedEntry]:
    entries: list[FeedEntry] = []
    for entry in _iter_children(root, "entry"):
        title = _clean_text(_find_text(entry, "title"))
        summary = _clean_text(_find_text(entry, "summary", "content"))
        link = _extract_atom_link(entry)
        published = _find_text(entry, "updated", "published")
        source = _extract_host(link) or _extract_host(fallback_source_url)

        if not title and not summary:
            continue
        if not title:
            title = summary[:180]
        if not summary:
            summary = title

        entries.append(
            FeedEntry(
                title=title,
                summary=summary,
                link=link,
                published=published,
                source=source,
            )
        )
    return entries


def _extract_atom_link(entry: ET.Element) -> str:
    for child in entry:
        if _tag_name(child.tag) != "link":
            continue
        rel = (child.attrib.get("rel") or "alternate").lower()
        href = child.attrib.get("href", "").strip()
        if href and rel in {"alternate", "self"}:
            return href
    for child in entry:
        if _tag_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        if href:
            return href
        if child.text:
            return child.text.strip()
    return ""


def _find_text(node: ET.Element, *names: str) -> str:
    targets = {name.lower() for name in names}
    for child in node:
        if _tag_name(child.tag) in targets:
            return "".join(child.itertext()).strip()
    return ""


def _find_child(node: ET.Element, name: str) -> ET.Element | None:
    target = name.lower()
    for child in node:
        if _tag_name(child.tag) == target:
            return child
    return None


def _iter_children(node: ET.Element, name: str) -> list[ET.Element]:
    target = name.lower()
    return [child for child in node if _tag_name(child.tag) == target]


def _extract_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1].lower()


def _clean_text(text: str) -> str:
    stripped = HTML_TAG_PATTERN.sub(" ", text)
    unescaped = unescape(stripped)
    return WHITESPACE_PATTERN.sub(" ", unescaped).strip()
