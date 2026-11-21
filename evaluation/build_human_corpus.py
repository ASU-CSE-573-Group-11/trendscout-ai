"""Build a deterministic 40-50 document candidate corpus for human annotation."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence


def build_corpus(records: Iterable[dict], limit: int = 45) -> list[dict]:
    if not 40 <= limit <= 50:
        raise ValueError("human annotation corpus size must be between 40 and 50")

    by_type: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for record in records:
        record_id = record["record_id"]
        if record_id in seen:
            continue
        seen.add(record_id)
        by_type.setdefault(record["source_type"], []).append(record)

    chosen: list[dict] = []
    while sum(len(items) for items in by_type.values()) and len(chosen) < limit:
        for source_type in sorted(by_type):
            if by_type[source_type] and len(chosen) < limit:
                chosen.append(by_type[source_type].pop(0))

    documents = []
    for record in chosen:
        documents.append({
            "document_id": record["record_id"],
            "company_id": record.get("company_id"),
            "source_type": record["source_type"],
            "source_url": record["source_url"],
            "title": record.get("title"),
            "span_text": record.get("text"),
            "event_at": record.get("event_at"),
            "published_at": record.get("published_at"),
            "observed_at": record["observed_at"],
        })
    return documents


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--limit", type=int, default=45)
    parser.add_argument("--out", type=Path, default=Path("evaluation/human-corpus.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = [
        json.loads(line)
        for line in args.snapshot.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    documents = build_corpus(records, args.limit)
    payload = {
        "snapshot": str(args.snapshot),
        "status": "machine_selected_pending_human_review",
        "document_count": len(documents),
        "documents": documents,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"document_count": len(documents), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
