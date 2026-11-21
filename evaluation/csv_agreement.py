"""Compute agreement from two filled human evidence or entity CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.compute_agreement import cohen_kappa


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--label-column", default="evidence_state")
    parser.add_argument("--item-column", default="item_id")
    return parser


def load_csv(path: Path, item_column: str, label_column: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            item = (row.get(item_column) or "").strip()
            label = (row.get(label_column) or "").strip()
            if item in seen:
                raise ValueError(f"duplicate item id in {path}: {item}")
            if item:
                seen.add(item)
            if item and label:
                labels[item] = label
    return labels


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        first = load_csv(args.first, args.item_column, args.label_column)
        second = load_csv(args.second, args.item_column, args.label_column)
        if set(first) != set(second) or len(first) < 100:
            raise ValueError("100+ shared items with identical item sets are required")
        kappa, shared = cohen_kappa(first, second)
    except ValueError as exc:
        print(f"Cannot compute kappa: {exc}")
        return 2
    if not first or not second:
        print("Cannot compute kappa: one or both CSV files have no labels.")
        return 2
    print(json.dumps({
        "shared_items": shared,
        "cohen_kappa": round(kappa, 6),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
