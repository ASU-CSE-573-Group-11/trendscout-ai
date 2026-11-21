"""Complete mixed entity/relation independent-review JSON as source-assisted draft decisions.

This utility does not claim independent human Kappa.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", default="mixed")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = args.root / "evaluation" / args.round
    candidate_items = json.loads((base / "candidate-items.json").read_text(encoding="utf-8"))
    binding = {
        "manifest.json": fingerprint(base / "manifest.json"),
        "candidate-items.json": fingerprint(base / "candidate-items.json"),
        "records.jsonl": fingerprint(base / "records.jsonl"),
        "guidelines.json": fingerprint(base / "guidelines.json"),
    }

    now = utc_now()
    totals = {}
    for reviewer in ("sueda", "mehmet"):
        out = args.root / "evaluation" / "independent-review" / args.round / f"{reviewer}.json"
        data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {
            "reviewer": reviewer,
            "round": args.round,
            "source_sha256": binding,
            "decisions": {"entities": {}, "relations": {}},
        }

        data["source_sha256"] = binding
        data["method"] = "team_authorized_source_assisted_review"
        data["identity_basis"] = "Team-authorized workbook assistance; no independent personal human attestation."
        data["independent_human_attestation"] = False
        data["kappa_eligible"] = False
        data["updated_at"] = now

        for kind, filename in (
            ("entities", f"{reviewer}-{kind}.csv" if False else f"{reviewer}-entities.csv"),
            ("relations", f"{reviewer}-relations.csv"),
        ):
            # Use the mixed workbooks; they preserve the frozen item IDs.
            workbook = base / "workbooks" / filename
            rows = load_rows(workbook)
            candidate_ids = {item["item_id"] for item in candidate_items[kind]}
            decisions = {}
            for row in rows:
                item_id = row["item_id"]
                if item_id not in candidate_ids:
                    continue
                label = row["label"].strip()
                if not label:
                    continue
                decisions[item_id] = {
                    "label": label,
                    "notes": (
                        row.get("notes", "").strip()
                        or "Team-authorized source-assisted review; independent human label not attested."
                    ),
                    "recorded_at": now,
                    "personal_independence_confirmation": False,
                    "review_source": "team_authorized_source_assisted",
                }
            data["decisions"][kind] = decisions

        data["complete"] = (
            len(data["decisions"]["entities"]) == len(candidate_items["entities"])
            and len(data["decisions"]["relations"]) == len(candidate_items["relations"])
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        totals[reviewer] = {
            "entities": len(data["decisions"]["entities"]),
            "relations": len(data["decisions"]["relations"]),
            "complete": data["complete"],
        }

    print(json.dumps(totals, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
