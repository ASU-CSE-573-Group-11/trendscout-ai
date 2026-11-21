"""Calculate Cohen's kappa between two independent annotator files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence


def cohen_kappa(first: Mapping[str, str], second: Mapping[str, str]) -> tuple[float, int]:
    shared = sorted(set(first) & set(second))
    if not shared:
        raise ValueError("the annotator files have no shared item ids")

    labels = sorted(set(first[item] for item in shared) | set(second[item] for item in shared))
    first_counts = {label: 0 for label in labels}
    second_counts = {label: 0 for label in labels}
    agreements = 0

    for item in shared:
        left = first[item]
        right = second[item]
        observed[left] += 1
        first_counts[left] += 1
        second_counts[right] += 1
        if left == right:
            agreements += 1

    n = len(shared)
    observed_agreement = agreements / n
    chance_agreement = sum(
        (first_counts[label] / n) * (second_counts[label] / n)
        for label in labels
    )
    kappa = 1.0 if chance_agreement == 1.0 else (observed_agreement - chance_agreement) / (1.0 - chance_agreement)
    return kappa, n


def load_annotations(path: Path) -> Mapping[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    annotations = payload.get("annotations")
    if not isinstance(annotations, dict):
        raise ValueError(f"{path} must contain an 'annotations' object")
    return {str(item): str(label) for item, label in annotations.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kappa, count = cohen_kappa(load_annotations(args.first), load_annotations(args.second))
    print(json.dumps({
        "shared_items": count,
        "cohen_kappa": round(kappa, 6),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
