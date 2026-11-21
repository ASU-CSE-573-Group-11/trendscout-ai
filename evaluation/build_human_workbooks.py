"""Build fillable human annotation workbooks for independent adjudication."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Sequence


EVIDENCE_STATES = ("emerging", "corroborated", "disputed", "stale", "insufficient")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("evaluation/human-workbooks"))
    return parser


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    worklist = json.loads(
        (Path("evaluation/annotation-worklist.json")).read_text(encoding="utf-8")
    )
    evidence_rows = [
        {
            "item_id": item["item_id"],
            "document_id": item.get("document_id") or "",
            "span_text": item["span_text"],
            "event_at": item.get("event_at") or "",
            "published_at": item.get("published_at") or "",
            "observed_at": item.get("observed_at") or "",
            "evidence_state": "",
        }
        for item in worklist["items"]
    ]

    evidence_fields = [
        "item_id",
        "document_id",
        "span_text",
        "event_at",
        "published_at",
        "observed_at",
        "evidence_state",
    ]
    write_csv(args.out_dir / "sueda-evidence.csv", evidence_fields, evidence_rows)
    write_csv(args.out_dir / "mehmet-evidence.csv", evidence_fields, evidence_rows)

    write_csv(
        args.out_dir / "sueda-entities.csv",
        ["item_id", "document_id", "span_text", "entity_type", "entity_text", "start", "end"],
        [],
    )
    write_csv(
        args.out_dir / "mehmet-entities.csv",
        ["item_id", "document_id", "span_text", "entity_type", "entity_text", "start", "end"],
        [],
    )
    write_csv(
        args.out_dir / "sueda-relations.csv",
        ["item_id", "document_id", "subject", "relation_type", "object", "span_text"],
        [],
    )
    write_csv(
        args.out_dir / "mehmet-relations.csv",
        ["item_id", "document_id", "subject", "relation_type", "object", "span_text"],
        [],
    )

    write_csv(
        args.out_dir / "qrels-adjudication.csv",
        ["question_id", "record_id", "grade", "adjudicator", "notes"],
        [],
    )

    print(json.dumps({
        "out_dir": str(args.out_dir),
        "evidence_rows": len(evidence_rows),
        "allowed_evidence_states": list(EVIDENCE_STATES),
        "entity_target": "200+",
        "relation_target": "80-100",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
