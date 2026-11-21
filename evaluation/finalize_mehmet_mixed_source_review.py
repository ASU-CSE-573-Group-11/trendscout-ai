"""Copy Sueda's source-assisted mixed labels into Mehmet's workbooks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Sequence


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_labels(source: Path, target: Path) -> tuple[int, int]:
    with source.open(newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle))
    with target.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        target_rows = list(reader)

    labels = {row["item_id"]: (row["label"], row["notes"]) for row in source_rows}
    filled = 0
    for row in target_rows:
        item_id = row["item_id"]
        if item_id in labels:
            label, notes = labels[item_id]
            row["label"] = label
            row["notes"] = (
                "Source-assisted copy of Sueda Sen's review. "
                "Independent human annotation not asserted."
                if not notes
                else notes + " | Source-assisted copy of Sueda Sen."
            )
            filled += 1

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(target_rows)
    accepted = sum(row["label"].strip() not in ("", "NONE") for row in target_rows)
    return filled, accepted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("evaluation/mixed"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workbooks = args.directory / "workbooks"

    sueda_entities = workbooks / "sueda-entities.csv"
    mehmet_entities = workbooks / "mehmet-entities.csv"
    sueda_relations = workbooks / "sueda-relations.csv"
    mehmet_relations = workbooks / "mehmet-relations.csv"

    entity_filled, entities_accepted = copy_labels(sueda_entities, mehmet_entities)
    relation_filled, relations_accepted = copy_labels(sueda_relations, mehmet_relations)

    attestation_path = workbooks / "mehmet-attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation.update({
        "status": "source_assisted_review_complete",
        "method": "team_source_assisted_assistance",
        "independent": False,
        "completed_at": "2026-11-21T10:30:00Z",
        "review_status": "source_assisted_labels_completed",
        "independent_human_attestation": False,
        "kappa_eligible": False,
        "scope": "Source-assisted copy of Sueda Sen's completed workbooks. Independent Mehmet personal annotation is not asserted.",
        "entity_decisions": entity_filled,
        "relation_decisions": relation_filled,
        "entities_accepted": entities_accepted,
        "relations_accepted": relations_accepted,
        "workbook_sha256": {
            "entities": sha(mehmet_entities),
            "relations": sha(mehmet_relations),
        },
    })
    attestation_path.write_text(
        json.dumps(attestation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    progress = {
        "reviewer": "Mehmet Aksit",
        "round": "mixed",
        "source_assisted_entities": entity_filled,
        "source_assisted_relations": relation_filled,
        "accepted_entities": entities_accepted,
        "accepted_relations": relations_accepted,
        "independent_human_attestation": False,
        "kappa_eligible": False,
    }
    out = args.directory / "mehmet-source-assisted-review.json"
    out.write_text(json.dumps(progress, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(progress, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
