from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from collectors.records import validate_record
from retrieval.bm25 import BM25Index


def load_records_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load an accepted collection snapshot and fail loudly on invalid records."""
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path} line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"record in {path} line {line_number} is not an object")
        errors = validate_record(record)
        if errors:
            raise ValueError(f"invalid record in {path} line {line_number}: {errors}")
        records.append(record)
    return records


def search_snapshot(
    records: Iterable[dict[str, Any]],
    query: str,
    *,
    k: int = 5,
    distinct_origins: bool = True,
) -> list[dict[str, Any]]:
    """Search records while optionally preventing syndicated copies from crowding results."""
    if k < 1:
        raise ValueError("k must be at least 1")
    hits = BM25Index.from_records(records).search(query, k=None if distinct_origins else k)
    if not distinct_origins:
        return hits[:k]

    selected: list[dict[str, Any]] = []
    seen_origins: set[str] = set()
    for hit in hits:
        origin = hit["origin_cluster_id"]
        if origin in seen_origins:
            continue
        seen_origins.add(origin)
        selected.append(hit)
        if len(selected) == k:
            break
    return selected


def graph_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Project a source record into the provenance fields consumed by the graph."""
    errors = validate_record(record)
    if errors:
        raise ValueError(f"cannot project invalid record {record.get('record_id')}: {errors}")
    return {
        "record_id": record["record_id"],
        "company_id": record["company_id"],
        "source_type": record["source_type"],
        "source_url": record["source_url"],
        "publisher": record.get("publisher"),
        "title": record.get("title"),
        "text": record.get("text"),
        "event_at": record.get("event_at"),
        "published_at": record.get("published_at"),
        "observed_at": record["observed_at"],
        "content_hash": record["content_hash"],
        "origin_cluster_id": record["origin_cluster_id"],
        "collector_version": record["collector_version"],
    }
