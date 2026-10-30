from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from collectors.records import canonicalize_url, sha256_text

_WORD = re.compile(r"[a-z0-9]+")
TITLE_JACCARD = 0.82


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"^(exclusive|breaking|update|analysis):\s*", "", text)
    return " ".join(_WORD.findall(text))


def tokenize(text: str | None) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def assign_origin_clusters(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge syndicated copies into one origin without dropping the records."""
    by_hash: dict[str, str] = {}
    by_url: dict[str, str] = {}
    clusters: dict[str, str] = {}

    for record in records:
        content_hash = record["content_hash"]
        canonical = canonicalize_url(record["source_url"])
        if content_hash in by_hash:
            clusters[record["record_id"]] = by_hash[content_hash]
            continue
        if canonical in by_url:
            clusters[record["record_id"]] = by_url[canonical]
            continue
        cluster_id = sha256_text(canonical)[:16]
        by_hash[content_hash] = cluster_id
        by_url[canonical] = cluster_id
        clusters[record["record_id"]] = cluster_id

    by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        record["origin_cluster_id"] = clusters[record["record_id"]]
        record.setdefault("metadata", {})
        record["metadata"]["canonical_url"] = canonicalize_url(record["source_url"])
        by_cluster[record["origin_cluster_id"]].append(record)

    titles: list[tuple[dict[str, Any], set[str], datetime | None]] = []
    for record in records:
        tokens = tokenize(normalize_title(record.get("title")))
        titles.append((record, tokens, _parse_ts(record.get("published_at") or record.get("observed_at"))))

    parent: dict[str, str] = {record["origin_cluster_id"]: record["origin_cluster_id"] for record in records}

    def find(cluster_id: str) -> str:
        while parent[cluster_id] != cluster_id:
            parent[cluster_id] = parent[parent[cluster_id]]
            cluster_id = parent[cluster_id]
        return cluster_id

    for i, (left, left_tokens, left_time) in enumerate(titles):
        for right, right_tokens, right_time in titles[i + 1 :]:
            if find(left["origin_cluster_id"]) == find(right["origin_cluster_id"]):
                continue
            if left.get("publisher") and left.get("publisher") == right.get("publisher"):
                continue
            if jaccard(left_tokens, right_tokens) < TITLE_JACCARD:
                continue
            if left_time and right_time and abs((left_time - right_time).days) > 7:
                continue
            root_left = find(left["origin_cluster_id"])
            root_right = find(right["origin_cluster_id"])
            parent[root_right] = root_left

    for record in records:
        root = find(record["origin_cluster_id"])
        record["origin_cluster_id"] = root
        record["metadata"]["origin_member_count"] = 0

    counts: dict[str, int] = defaultdict(int)
    for record in records:
        counts[record["origin_cluster_id"]] += 1
    for record in records:
        record["metadata"]["origin_member_count"] = counts[record["origin_cluster_id"]]
        record["metadata"]["independent_origin"] = counts[record["origin_cluster_id"]] == 1 or record["record_id"] == min(
            item["record_id"] for item in records if item["origin_cluster_id"] == record["origin_cluster_id"]
        )
    return records


def independent_origin_count(records: list[dict[str, Any]]) -> int:
    return len({record["origin_cluster_id"] for record in records})
