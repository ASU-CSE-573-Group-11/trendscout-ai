"""Finalize the source-assisted Sueda relation review without pretending it is independent."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Sequence


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path("evaluation/mixed"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workbooks = args.directory / "workbooks"
    relations_path = workbooks / "sueda-relations.csv"
    attestation_path = workbooks / "sueda-attestation.json"

    with relations_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if len(rows) != 108:
        raise ValueError(f"expected 108 relation decisions, found {len(rows)}")

    allowed = {"MENTIONS", "NONE"}
    invalid = [row["item_id"] for row in rows if row["label"].strip() not in allowed]
    if invalid:
        raise ValueError(f"invalid relation labels: {invalid[:5]}")

    mentions = sum(row["label"].strip() == "MENTIONS" for row in rows)
    rejected = sum(row["label"].strip() == "NONE" for row in rows)

    summary = json.loads(
        (args.directory / "sueda-source-review/summary.json").read_text(encoding="utf-8")
    )
    summary["relations_reviewed"] = len(rows)
    summary["mentions_accepted"] = mentions
    summary["relations_rejected"] = rejected
    summary["sueda_relations_status"] = "source_assisted_review_complete"
    summary["independent_human_agreement"] = None
    (args.directory / "sueda-source-review/summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["status"] = "source_review_complete"
    attestation["independent"] = False
    attestation["scope"] = (
        "First source-assisted mixed-round relation review by the Sueda-assigned workbook. "
        "Independent personal annotation is not attested."
    )
    attestation["accepted_relations"] = mentions
    attestation["rejected_relations"] = rejected
    attestation["workbook_sha256"]["relations"] = sha(relations_path)
    attestation_path.write_text(
        json.dumps(attestation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    progress = {
        "reviewer": "Sueda Sen",
        "round": "mixed",
        "relation_decisions": len(rows),
        "mentions": mentions,
        "none": rejected,
        "method": "source_assisted_review",
        "independent_human_attestation": False,
        "kappa_eligible": False,
        "workbook_sha256": sha(relations_path),
    }
    out = args.directory / "sueda-source-review/relation-review-complete.json"
    out.write_text(json.dumps(progress, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(progress, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
