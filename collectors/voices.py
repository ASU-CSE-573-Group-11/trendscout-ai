from __future__ import annotations

from typing import Any

from collectors.cohort import alias_index, included_companies, match_companies
from collectors.http import FetchError
from collectors.records import make_record
from collectors.rss import iter_feed, parse_feed


def _voice_label(source: dict[str, Any], title: str | None, text: str | None) -> str:
    haystack = f"{title or ''} {text or ''}".lower()
    if "interview" in haystack:
        return "interview"
    if any(token in haystack for token in ("opinion", "why i", "i think")):
        return "opinion"
    return source.get("default_label") or "analysis"


def collect_voices(
    named_sources: dict[str, Any],
    cohort: dict[str, Any],
    *,
    live: bool = True,
    feed_bodies: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    aliases = alias_index(included_companies(cohort))
    records: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []

    for source in named_sources.get("public_voices", []):
        source_id = source["source_id"]
        rss_url = source["rss_url"]
        try:
            if live:
                entries = list(iter_feed(rss_url))
            else:
                body = (feed_bodies or {}).get(source_id)
                if body is None:
                    raise FetchError(f"missing offline fixture for {source_id}")
                entries = parse_feed(body, rss_url)
        except FetchError as exc:
            coverage.append({"source_id": source_id, "status": "unavailable", "detail": str(exc)})
            continue

        kept = 0
        for entry in entries:
            haystack = f"{entry.get('title') or ''} {entry.get('summary') or ''}"
            matches = match_companies(haystack, aliases)
            if not matches:
                continue
            company_id, startup_name = matches[0]
            voice_label = _voice_label(source, entry.get("title"), entry.get("summary"))
            records.append(
                make_record(
                    source_type="public_voice",
                    source_url=entry["url"],
                    title=entry.get("title"),
                    text=entry.get("summary"),
                    publisher=source.get("publisher") or entry.get("publisher"),
                    company_id=company_id,
                    startup_name=startup_name,
                    event_type=voice_label,
                    published_at=entry.get("published_at"),
                    access_note=source.get("access_note"),
                    metadata={
                        "source_id": source_id,
                        "voice_label": voice_label,
                        "matched_company_ids": [item[0] for item in matches],
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
