"""Refuse to report final human-evaluation success until human-only gates are complete."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_json(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"missing file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def validate(root: Path) -> list[str]:
    if (root / "evaluation/real/manifest.json").exists():
        from evaluation.real_round import validate as validate_real_round
        return validate_real_round(root / "evaluation/real")
    errors: list[str] = []

    corpus = load_json(root / "evaluation/human-corpus.json")
    count = int(corpus.get("document_count", 0))
    if not 40 <= count <= 50:
        errors.append("human corpus must contain 40-50 documents")
    if corpus.get("status") != "joint_human_selection_complete":
        errors.append("human corpus has not been reviewed")
    if corpus.get("synthetic_fixture") is not False:
        errors.append("human corpus must contain real source documents, not synthetic fixtures")

    entity_relation = load_json(root / "evaluation/entity-relation.template.json")
    if len(entity_relation.get("entities", [])) < 200:
        errors.append("at least 200 human-labelled entity mentions are required")
    if not 80 <= len(entity_relation.get("relations", [])) <= 100:
        errors.append("human-labelled relations must be 80-100")
    if entity_relation.get("status") != "human_annotation_complete":
        errors.append("entity/relation human annotation is not complete")

    agreement = load_json(root / "evaluation/annotation_agreement.json")
    if agreement.get("status") != "human_review_complete":
        errors.append("independent human agreement is not complete")
    if agreement.get("shared_items", 0) < 100:
        errors.append("human agreement must cover at least 100 shared items")

    qrels_path = root / "evaluation/adjudicated-qrels.template.json"
    qrels = load_json(qrels_path)
    if qrels.get("illustrative") is not False:
        errors.append("qrels must not remain illustrative")
    if qrels.get("status") != "human_adjudicated":
        errors.append("qrels are not human adjudicated")
    if not qrels.get("qrels"):
        errors.append("adjudicated qrels are empty")

    pilot = load_json(root / "evaluation/trust-pilot.template.json")
    participants = pilot.get("participants", [])
    tasks = pilot.get("task_results", [])
    if not 5 <= len(participants) <= 8:
        errors.append("trust pilot requires 5-8 participants")
    if not tasks:
        errors.append("trust pilot task results are missing")

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
        print(f"Cannot validate final human evaluation: {exc}")
        return 2
    if errors:
        print("Human evaluation is incomplete:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Human evaluation gates complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
