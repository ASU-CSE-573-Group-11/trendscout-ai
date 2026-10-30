from __future__ import annotations

from typing import Any

from collectors.cohort import alias_index, included_companies, match_companies
from collectors.http import FetchError
from collectors.records import make_record
from collectors.rss import iter_feed


def collect_news(
    named_sources: dict[str, Any],
    cohort: dict[str, Any],
    *,
    live: bool = True,
    feed_bodies: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    companies = included_companies(cohort)
    aliases = alias_index(companies)
    records: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []

    for source in named_sources.get("news", []):
        rss_url = source["rss_url"]
        source_id = source["source_id"]
        try:
            if live:
                entries = list(iter_feed(rss_url))
            else:
                from collectors.rss import parse_feed

                body = (feed_bodies or {}).get(source_id)
                if body is None:
                    raise FetchError(f"missing offline fixture for {source_id}")
                entries = parse_feed(body, rss_url)
        except FetchError as exc:
            coverage.append(
                {
                    "source_id": source_id,
                    "status": "unavailable",
                    "detail": str(exc),
                }
            )
            continue

        kept = 0
        for entry in entries:
            haystack = f"{entry.get('title') or ''} {entry.get('summary') or ''}"
            matches = match_companies(haystack, aliases)
            if not matches:
                continue
            company_id, startup_name = matches[0]
            records.append(
                make_record(
                    source_type="news",
                    source_url=entry["url"],
                    title=entry.get("title"),
                    text=entry.get("summary"),
                    publisher=source.get("publisher") or entry.get("publisher"),
                    company_id=company_id,
                    startup_name=startup_name,
                    event_type="news_mention",
                    published_at=entry.get("published_at"),
                    access_note=source.get("access_note"),
                    metadata={
                        "source_id": source_id,
                        "matched_company_ids": [item[0] for item in matches],
                        "refresh": source.get("refresh"),
                    },
                )
            )
            kept += 1
        coverage.append(
            {
                "source_id": source_id,
                "status": "ok",
                "entries_seen": len(entries),
                "entries_kept": kept,
            }
        )
    return records, coverage
