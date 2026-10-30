from __future__ import annotations

from typing import Any

from collectors.cohort import included_companies
from collectors.http import FetchError
from collectors.records import make_record
from collectors.rss import iter_feed, parse_feed


def collect_company_newsrooms(
    cohort: dict[str, Any],
    *,
    live: bool = True,
    feed_bodies: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []

    for company in included_companies(cohort):
        rss_url = company.get("rss_url")
        newsroom_url = company.get("newsroom_url")
        source_id = f"company:{company['company_id']}"
        if not rss_url:
            coverage.append(
                {
                    "source_id": source_id,
                    "status": "skipped",
                    "detail": "No documented RSS URL in the frozen cohort registry.",
                }
            )
            continue
        try:
            if live:
                entries = list(iter_feed(rss_url))
            else:
                body = (feed_bodies or {}).get(company["company_id"])
                if body is None:
                    raise FetchError(f"missing offline fixture for {company['company_id']}")
                entries = parse_feed(body, rss_url)
        except FetchError as exc:
            coverage.append({"source_id": source_id, "status": "unavailable", "detail": str(exc)})
            continue

        for entry in entries:
            records.append(
                make_record(
                    source_type="company",
                    source_url=entry["url"],
                    title=entry.get("title"),
                    text=entry.get("summary"),
                    publisher=company["name"],
                    company_id=company["company_id"],
                    startup_name=company["name"],
                    event_type="company_announcement",
                    published_at=entry.get("published_at"),
                    access_note="Official newsroom or RSS. Company statements need an independent origin before corroboration.",
                    metadata={
                        "newsroom_url": newsroom_url,
                        "rss_url": rss_url,
                        "domain": company.get("domain"),
                    },
                )
            )
        coverage.append(
            {
                "source_id": source_id,
                "status": "ok",
                "entries_seen": len(entries),
                "entries_kept": len(entries),
            }
        )
    return records, coverage
