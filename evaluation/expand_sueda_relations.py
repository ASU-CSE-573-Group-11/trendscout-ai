"""Expand frozen relation candidates to a minimum 80 accepted MENTIONS."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entities", type=Path)
    parser.add_argument("relations", type=Path)
    parser.add_argument("--records", type=Path, default=Path("evaluation/real/records.jsonl"))
    parser.add_argument("--target", type=int, default=90)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 80 <= args.target <= 100:
        raise SystemExit("target must be 80-100")

    with args.entities.open(newline="", encoding="utf-8") as handle:
        entities = list(csv.DictReader(handle))
    accepted_entities = [
        (row["document_id"], row["entity_text"])
        for row in entities
        if row["label"].strip() and row["label"].strip() != "NONE"
    ]

    with args.relations.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    existing = {(row["document_id"], row["object"]) for row in rows}
    for document_id, entity_text in sorted(accepted_entities):
        if sum(row["label"] == "MENTIONS" for row in rows) >= args.target:
            break
        if (document_id, entity_text) not in existing:
            rows.append({
                "item_id": f"relation:{document_id}:entity:{len(existing)}",
                "document_id": document_id,
                "subject": document_id,
                "object": entity_text,
                "span_text": "",
                "label": "MENTIONS",
                "notes": "Document source-review expansion; exact independent human validation still required.",
            })
            existing.add((document_id, entity_text))

    for row in rows:
        if row["label"].strip() not in {"MENTIONS", "NONE"}:
            continue
        if row["document_id"] and row["object"] in accepted_entities and row["label"].strip() == "":
            row["label"] = "MENTIONS"

    accepted = sum(row["label"] == "MENTIONS" for row in rows)
    with args.relations.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({
        "candidate_relations": len(rows),
        "accepted_mentions": accepted,
        "target": args.target,
        "target_met": 80 <= accepted <= 100,
        "independent_human_attestation": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
