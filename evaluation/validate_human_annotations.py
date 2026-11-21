"""Validate independent Sueda/Mehmet entity and relation workbooks."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable, Sequence


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ValueError(f"missing workbook: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle)]


def validate(root: Path) -> list[str]:
    workbook = root / "evaluation/human-workbooks"
    errors: list[str] = []

    sueda_entities = read_rows(workbook / "sueda-entities-work.csv")
    mehmet_entities = read_rows(workbook / "mehmet-entities-work.csv")
    sueda_entities = [row for row in sueda_entities if row.get("entity_text", "").strip()]
    mehmet_entities = [row for row in mehmet_entities if row.get("entity_text", "").strip()]
    if len(sueda_entities) < 200 or len(mehmet_entities) < 200:
        errors.append("Sueda and Mehmet need at least 200 entity mentions each")

    sueda_relations = read_rows(workbook / "sueda-relations-work.csv")
    mehmet_relations = read_rows(workbook / "mehmet-relations-work.csv")
    sueda_relations = [
        row for row in sueda_relations
        if row.get("subject", "").strip() and row.get("relation_type", "").strip() and row.get("object", "").strip()
    ]
    mehmet_relations = [
        row for row in mehmet_relations
        if row.get("subject", "").strip() and row.get("relation_type", "").strip() and row.get("object", "").strip()
    ]
    for name, rows in (
        ("Sueda", sueda_relations),
        ("Mehmet", mehmet_relations),
    ):
        if not 80 <= len(rows) <= 100:
            errors.append(f"{name} needs 80-100 independent relations; got {len(rows)}")

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        errors = validate(args.root)
    except ValueError as exc:
        print(f"Cannot validate human annotations: {exc}")
        return 2
    if errors:
        print("Human annotation is incomplete:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Human entity/relation annotation gates complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
