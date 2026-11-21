import csv
import json
from collections import Counter
from pathlib import Path

from graph.rdf import graph_payload_to_rdf
from graph.real_projection import build_real_graph
from graph.shacl import validate_graph
from evaluation.real_graph_integration import check_output


ROOT = Path(__file__).resolve().parents[1]
MIXED = ROOT / "evaluation" / "mixed"


def _payload():
    records = [json.loads(line) for line in (MIXED / "records.jsonl").read_text().splitlines() if line]
    with (MIXED / "workbooks" / "sueda-entities.csv").open(newline="", encoding="utf-8") as handle:
        entities = list(csv.DictReader(handle))
    return build_real_graph(records, entities)


def test_real_projection_populates_required_semantic_classes_from_frozen_sources():
    payload = _payload()
    labels = Counter(node["label"] for node in payload["nodes"])
    assert labels == {
        "Claim": 45,
        "FundingRound": 3,
        "Investor": 4,
        "JobPosting": 18,
        "OriginCluster": 24,
        "Publisher": 5,
        "Repository": 3,
        "Skill": 10,
        "SourceRecord": 45,
        "Startup": 5,
        "Technology": 8,
    }
    assert len(payload["nodes"]) == 170
    assert len(payload["edges"]) == 466


def test_projection_preserves_observation_limits_instead_of_inventing_events():
    payload = _payload()
    rounds = [node for node in payload["nodes"] if node["label"] == "FundingRound"]
    postings = [node for node in payload["nodes"] if node["label"] == "JobPosting"]
    assert all("event_at" not in node["properties"] for node in rounds)
    assert all(node["properties"]["observed_at"] for node in rounds + postings)
    assert not any(edge["type"] == "PARTICIPATED_IN" for edge in payload["edges"])
    assert sum(edge["type"] == "BACKS" for edge in payload["edges"]) == 4


def test_complete_real_graph_conforms_to_expanded_shacl_shapes():
    conforms, _, report = validate_graph(graph_payload_to_rdf(_payload()))
    assert conforms is True, report


def test_checked_in_real_graph_artifacts_replay_exactly():
    check_output(MIXED, MIXED / "real-graph-integration")
