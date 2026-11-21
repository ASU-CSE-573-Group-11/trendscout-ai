from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from rdflib import Graph
from rdflib.compare import isomorphic

from evaluation.real_round import ROOT
from graph.rdf import graph_payload_to_rdf, serialize_graph_payload
from graph.real_projection import build_real_graph
from graph.shacl import validate_graph


DEFAULT_DIRECTORY = ROOT / "evaluation" / "mixed"
DEFAULT_OUTPUT = DEFAULT_DIRECTORY / "real-graph-integration"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_inputs(directory: Path) -> tuple[list[dict], list[dict[str, str]]]:
    records_path = directory / "records.jsonl"
    entities_path = directory / "workbooks" / "sueda-entities.csv"
    records = [json.loads(line) for line in records_path.read_text().splitlines() if line.strip()]
    with entities_path.open(newline="", encoding="utf-8") as handle:
        entities = list(csv.DictReader(handle))
    return records, entities


def artifacts(directory: Path = DEFAULT_DIRECTORY) -> tuple[dict, str, str, dict]:
    records, entities = _read_inputs(directory)
    payload = build_real_graph(records, entities)
    rdf_graph = graph_payload_to_rdf(payload)
    conforms, _, report = validate_graph(rdf_graph)
    if not conforms:
        raise ValueError(f"real semantic graph does not conform to SHACL:\n{report}")
    labels = Counter(node["label"] for node in payload["nodes"])
    relations = Counter(edge["type"] for edge in payload["edges"])
    summary = {
        "status": "real_source_graph_integration_complete",
        "source_snapshot_sha256": json.loads((directory / "manifest.json").read_text())[
            "snapshot_sha256"
        ],
        "inputs": {
            "records.jsonl": _sha(directory / "records.jsonl"),
            "workbooks/sueda-entities.csv": _sha(directory / "workbooks" / "sueda-entities.csv"),
        },
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "node_labels": dict(sorted(labels.items())),
        "edge_types": dict(sorted(relations.items())),
        "shacl_conforms": True,
        "live_neo4j_validation": "live-neo4j-validation.json",
        "reproducible_demo": "demo-results.json",
        "visual_demo": "demo.html",
        "documentation": "README.md",
        "source_record_count": len(records),
        "source_review_basis": "Sueda source-assisted entity review; not independent paired annotation.",
        "limitations": [
            "JobPosting nodes are observed public listings, not completed hires or headcount.",
            "FundingRound eventAt remains absent when the retained record has no reviewed event date.",
            "Investor BACKS edges require an exact retained 'backed by leading investors including' context; no investor is assigned to a specific FundingRound.",
            "Claim nodes are source excerpts in emerging state, not independently adjudicated semantic gold.",
            "Repository activity windows do not establish product adoption or company growth.",
        ],
    }
    return payload, serialize_graph_payload(payload), report, summary


def write_output(directory: Path, output: Path, *, replace: bool = False) -> None:
    expected = {"graph.json", "records.ttl", "shacl-report.txt", "summary.json"}
    allowed = expected | {
        "live-neo4j-validation.json",
        "demo-results.json",
        "demo.html",
        "README.md",
    }
    if output.exists():
        existing = {path.name for path in output.iterdir()}
        if not replace:
            raise ValueError(f"refusing to overwrite existing output: {output}")
        if not expected.issubset(existing) or not existing.issubset(allowed):
            raise ValueError(f"refusing to replace unexpected output contents: {sorted(existing)}")
    payload, turtle, report, summary = artifacts(directory)
    output.mkdir(parents=True, exist_ok=replace)
    (output / "graph.json").write_text(json.dumps(payload, indent=2) + "\n")
    (output / "records.ttl").write_text(turtle.rstrip() + "\n")
    (output / "shacl-report.txt").write_text(report)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def check_output(directory: Path, output: Path) -> None:
    payload, _, report, summary = artifacts(directory)
    if json.loads((output / "graph.json").read_text()) != payload:
        raise ValueError("graph.json is stale")
    if json.loads((output / "summary.json").read_text()) != summary:
        raise ValueError("summary.json is stale")
    generated = graph_payload_to_rdf(payload)
    stored_turtle = Graph().parse(output / "records.ttl", format="turtle")
    if not isomorphic(stored_turtle, generated):
        raise ValueError("stored Turtle is not isomorphic to graph.json")
    if (output / "shacl-report.txt").read_text() != report:
        raise ValueError("SHACL report is stale")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "check"))
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.mode == "build":
        write_output(args.directory, args.out, replace=args.replace)
    else:
        check_output(args.directory, args.out)
    print(json.dumps({"status": "ok", "mode": args.mode, "output": str(args.out)}))


if __name__ == "__main__":
    main()
