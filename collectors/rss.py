from __future__ import annotations

from typing import Any, Iterator

import feedparser

from collectors.http import FetchError, fetch_text
from collectors.records import parse_datetime, strip_html


def parse_feed(body: str, source_url: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(body)
    if not parsed.get('version') or parsed.get('bozo'):
        raise FetchError(f'invalid RSS/Atom feed: {source_url}')
    entries: list[dict[str, Any]] = []
    for entry in parsed.entries:
        link = entry.get("link") or source_url
        title = strip_html(entry.get("title"))
        summary = strip_html(entry.get("summary") or entry.get("description"))
        published = None
        if entry.get("published"):
            published = parse_datetime(entry.get("published"))
        if not published and entry.get("published_parsed"):
            published = _struct_time_to_iso(entry.get("published_parsed"))
        # An update timestamp does not establish initial publication time.
        entries.append(
            {
                "url": link,
                "title": title or None,
                "summary": summary or None,
                "published_at": published,
                "publisher": parsed.feed.get("title"),
            }
        )
    return entries


def iter_feed(url: str) -> Iterator[dict[str, Any]]:
    body = fetch_text(url)
    if not body.strip():
        raise FetchError(f"empty feed: {url}")
    yield from parse_feed(body, url)


def _struct_time_to_iso(value: Any) -> str | None:
    if not value:
        return None
    try:
        return f"{value.tm_year:04d}-{value.tm_mon:02d}-{value.tm_mday:02d}T{value.tm_hour:02d}:{value.tm_min:02d}:{value.tm_sec:02d}Z"
    except AttributeError:
        return None
