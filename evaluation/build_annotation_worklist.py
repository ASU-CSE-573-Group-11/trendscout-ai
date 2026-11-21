"""Build a frozen-record annotation worklist with stable item ids."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence


def build_worklist(records: Iterable[dict]) -> list[dict]:
    items = []
    for record in records:
        record_id = record["record_id"]
        items.append({
            "item_id": f"annotation:{record_id}",
            "record_id": record_id,
            "document_id": record.get("source_record_id"),
            "span_text": "\n".join(
                part
                for part in (record.get("title"), record.get("text"))
                if isinstance(part, str) and part
            ),
            "event_at": record.get("event_at"),
            "published_at": record.get("published_at"),
            "observed_at": record.get("observed_at"),
        })
    return items


def load_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", type=Path, default=Path("evaluation/annotation-worklist.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    items = build_worklist(load_jsonl(args.snapshot))
    payload = {
        "snapshot": str(args.snapshot),
        "item_count": len(items),
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"item_count": len(items), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
