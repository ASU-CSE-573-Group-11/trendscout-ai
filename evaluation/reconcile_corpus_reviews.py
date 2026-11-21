"""Reconcile Sueda and Mehmet human corpus-review decisions."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Sequence


def load_decisions(path: Path) -> dict[str, str]:
    decisions: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            document_id = (row.get("document_id") or "").strip()
            decision = (row.get("include_in_final_corpus") or "").strip().lower()
            if document_id:
                decisions[document_id] = decision
    return decisions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sueda", type=Path)
    parser.add_argument("mehmet", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("evaluation/human-corpus.json"))
    parser.add_argument("--out", type=Path, default=Path("evaluation/final-human-corpus.json"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sueda = load_decisions(args.sueda)
    mehmet = load_decisions(args.mehmet)

    disagree = sorted(
        document_id
        for document_id in set(sueda) & set(mehmet)
        if sueda[document_id] != mehmet[document_id]
    )
    if disagree:
        print(json.dumps({
            "status": "disagreement_pending_adjudication",
            "disagreements": disagree,
        }, indent=2))
        return 2

    approved = sorted(
        document_id
        for document_id in set(sueda) & set(mehmet)
        if sueda[document_id] == "yes" and mehmet[document_id] == "yes"
    )
    if not 40 <= len(approved) <= 50:
        print(json.dumps({
            "status": "invalid_final_corpus_size",
            "approved_documents": len(approved),
        }, indent=2))
        return 2

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    by_id = {
        document["document_id"]: document
        for document in corpus.get("documents", [])
    }
    documents = [by_id[document_id] for document_id in approved if document_id in by_id]
    payload = {
        "snapshot": corpus.get("snapshot"),
        "status": "joint_human_selection_complete",
        "annotators": ["Sueda Sen", "Mehmet Aksit"],
        "document_count": len(documents),
        "synthetic_fixture": True,
        "human_selection_not_independent": True,
        "documents": documents,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "joint_human_selection_complete",
        "document_count": len(documents),
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
