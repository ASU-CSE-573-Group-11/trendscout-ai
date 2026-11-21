"""Create clearly labeled simulated annotation drafts for review.

These files are AI suggestions, not independent human annotations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def draft_label(record_id: str, source_type: str) -> str:
    if source_type == "github" and "mirror" in record_id.lower():
        return "insufficient"
    if source_type in {"github", "greenhouse", "lever", "news", "company", "public_voice", "job"}:
        return "emerging"
    return "insufficient"


def load_snapshot(path: Path) -> Mapping[str, str]:
    source_types: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        source_types[str(record["record_id"])] = str(record.get("source_type", ""))
    return source_types


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("worklist", type=Path)
    parser.add_argument("--first", type=Path, default=Path("evaluation/annotator-a.json"))
    parser.add_argument("--second", type=Path, default=Path("evaluation/annotator-b.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_types = load_snapshot(args.snapshot)
    worklist = json.loads(args.worklist.read_text(encoding="utf-8"))

    annotations: dict[str, str] = {}
    for item in worklist["items"]:
        record_id = str(item["record_id"])
        annotations[str(item["item_id"])] = draft_label(record_id, source_types.get(record_id, ""))

    unique_item_ids = sorted(set(annotations))
    for path, annotator in (
        (args.first, "Copilot simulated annotator A"),
        (args.second, "Copilot simulated annotator B"),
    ):
        path.write_text(json.dumps({
            "annotator": annotator,
            "status": "simulated",
            "generated_by": "GitHub Copilot",
            "generated_from": str(args.worklist),
            "not_human_annotation": True,
            "pending_item_ids": [],
            "annotations": annotations,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for label in annotations.values():
        counts[label] = counts.get(label, 0) + 1
    print(json.dumps({
        "unique_item_ids": len(unique_item_ids),
        "label_counts": counts,
        "first": str(args.first),
        "second": str(args.second),
        "warning": "SIMULATED LABELS ONLY - NOT HUMAN ANNOTATIONS",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
