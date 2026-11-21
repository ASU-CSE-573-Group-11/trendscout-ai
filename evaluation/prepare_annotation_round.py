"""Create independent annotator input files from a frozen worklist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worklist", type=Path)
    parser.add_argument("--first", type=Path, default=Path("evaluation/annotator-a.json"))
    parser.add_argument("--second", type=Path, default=Path("evaluation/annotator-b.json"))
    parser.add_argument("--first-name", default="ANNOTATOR_A")
    parser.add_argument("--second-name", default="ANNOTATOR_B")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(args.worklist.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"{args.worklist} must contain an items list")

    pending = sorted({str(item["item_id"]) for item in items})
    for path, name in (
        (args.first, args.first_name),
        (args.second, args.second_name),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "annotator": name,
            "status": "not_started",
            "pending_item_ids": pending,
            "annotations": {},
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "unique_item_ids": len(pending),
        "first": str(args.first),
        "second": str(args.second),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
