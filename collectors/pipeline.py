from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collectors.cohort import load_cohort, load_named_sources
from collectors.company import collect_company_newsrooms
from collectors.news import collect_news
from collectors.origin import assign_origin_clusters, independent_origin_count
from collectors.records import validate_records
from collectors.voices import collect_voices
from collectors.yc import collect_yc_identity
from collectors.youtube import collect_youtube


def merge_coverage(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for group in groups:
        merged.extend(group)
    return merged


def quarantine(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failures = validate_records(records)
    by_id = {record_id for record_id, _ in failures}
    accepted = [record for record in records if record["record_id"] not in by_id]
    rejected = [
        {
            "record_id": record_id,
            "errors": [message for failed_id, message in failures if failed_id == record_id],
        }
        for record_id in sorted(by_id)
    ]
    return accepted, rejected


def run_sueda_collection(
    *,
    live: bool = False,
    feed_bodies: dict[str, str] | None = None,
    company_feed_bodies: dict[str, str] | None = None,
    include_youtube: bool = False,
    cohort_path: Path | None = None,
    sources_path: Path | None = None,
) -> dict[str, Any]:
    cohort = load_cohort(cohort_path)
    named_sources = load_named_sources(sources_path)

    news_records, news_coverage = collect_news(
        named_sources, cohort, live=live, feed_bodies=feed_bodies
    )
    voice_records, voice_coverage = collect_voices(
        named_sources, cohort, live=live, feed_bodies=feed_bodies
    )
    company_records, company_coverage = collect_company_newsrooms(
        cohort, live=live, feed_bodies=company_feed_bodies
    )
    yc_records, yc_coverage = collect_yc_identity(cohort)
    youtube_records: list[dict[str, Any]] = []
    youtube_coverage: list[dict[str, Any]] = []
    if include_youtube:
        youtube_records, youtube_coverage = collect_youtube(cohort)

    raw = news_records + voice_records + company_records + yc_records + youtube_records
    clustered = assign_origin_clusters(raw)
    accepted, rejected = quarantine(clustered)

    return {
        "accepted": accepted,
        "rejected": rejected,
        "coverage": merge_coverage(
            news_coverage, voice_coverage, company_coverage, yc_coverage, youtube_coverage
        ),
        "stats": {
            "raw_count": len(raw),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "independent_origins": independent_origin_count(accepted),
            "live": live,
        },
        "cohort_frozen_at": cohort.get("frozen_at"),
    }


def write_collection_bundle(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "records.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=True) + "\n" for record in result["accepted"]),
        encoding="utf-8",
    )
    (output_dir / "quarantine.json").write_text(
        json.dumps(result["rejected"], indent=2), encoding="utf-8"
    )
    (output_dir / "coverage.json").write_text(
        json.dumps(result["coverage"], indent=2), encoding="utf-8"
    )
    (output_dir / "stats.json").write_text(
        json.dumps(result["stats"], indent=2), encoding="utf-8"
    )
