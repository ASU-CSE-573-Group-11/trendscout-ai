from __future__ import annotations

from typing import Any

from collectors.cohort import included_companies
from collectors.records import make_record, utc_now


def collect_yc_identity(cohort: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Emit freeze-time YC identity records. A directory listing is not a trend score."""
    records: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    frozen_at = cohort.get("frozen_at")

    for company in included_companies(cohort):
        yc_url = company.get("yc_url")
        if not yc_url:
            coverage.append(
                {
                    "source_id": f"yc:{company['company_id']}",
                    "status": "skipped",
                    "detail": "No YC directory URL recorded at freeze time.",
                }
            )
            continue
        passage = (
            f"{company['name']} is listed in the frozen TrendScout cohort. "
            f"Official domain: {company.get('domain')}. "
            f"YC directory: {yc_url}. "
            f"YC batch as recorded at freeze: {company.get('yc_batch') or 'not recorded'}. "
            "Directory presence confirms identity and category; it does not prove momentum."
        )
        records.append(
            make_record(
                source_type="reference",
                source_url=yc_url,
                title=f"{company['name']} Y Combinator directory identity",
                text=passage,
                publisher="Y Combinator",
                company_id=company["company_id"],
                startup_name=company["name"],
                event_type="identity",
                event_at=f"{frozen_at}T00:00:00Z" if frozen_at else None,
                published_at=f"{frozen_at}T00:00:00Z" if frozen_at else utc_now(),
                access_note=(
                    "Public YC company directory page recorded in the frozen cohort registry. "
                    "No bulk scrape of ycombinator.com is performed at collection time."
                ),
                metadata={
                    "yc_batch": company.get("yc_batch"),
                    "domain": company.get("domain"),
                    "category": company.get("category"),
                    "freeze_only": True,
                },
            )
        )
        coverage.append({"source_id": f"yc:{company['company_id']}", "status": "ok", "entries_kept": 1})
    return records, coverage
