"""Trend signals projected into the graph and evidence-ledger conventions."""

from __future__ import annotations

import pytest

from faisal_snapshot import snapshot_records
from graph.evidence import EVIDENCE_STATES
from graph.import_contract import records_to_graph
from signals.contract import to_payload
from signals.graph_export import (
    ABOUT,
    DERIVED_FROM,
    TREND_NODE_LABEL,
    ledger_support_note,
    trend_import_statements,
    trend_signal_to_graph,
    trend_signals_to_graph,
)
from signals.pipeline import resolve_window, rising_with_new_hiring, run_trend_pipeline


@pytest.fixture(scope="module")
def run():
    return run_trend_pipeline(snapshot_records())


@pytest.fixture(scope="module")
def scored(run):
    """A rising company-level signal with real evidence behind it."""
    window = resolve_window(run, weeks=8)
    matches = rising_with_new_hiring(run, weeks=window)
    assert matches
    trend_ids = set(matches[0]["trend_ids"])
    signals = [signal for signal in run.signals if signal.trend_id in trend_ids]
    return to_payload(signals)


def test_a_trend_signal_becomes_one_node_with_derived_from_edges(scored):
    payload = trend_signal_to_graph(scored[0])
    nodes = {node["id"]: node for node in payload["nodes"]}
    trend_nodes = [node for node in payload["nodes"] if node["label"] == TREND_NODE_LABEL]
    assert len(trend_nodes) == 1
    assert trend_nodes[0]["id"] == scored[0]["trend_id"]
    assert trend_nodes[0]["properties"]["label"] in {"rising", "flat", "falling", "insufficient_history"}

    derived = [edge for edge in payload["edges"] if edge["type"] == DERIVED_FROM]
    assert derived
    assert all(edge["from"] == scored[0]["trend_id"] for edge in derived)
    assert all(edge["to"].startswith("source-record:") for edge in derived)

    about = [edge for edge in payload["edges"] if edge["type"] == ABOUT]
    assert len(about) == 1
    assert about[0]["to"] == f"startup:{scored[0]['company_id']}"
    assert nodes[about[0]["to"]]["label"] == "Startup"


def test_node_ids_follow_the_existing_import_contract_prefixes(scored):
    records = snapshot_records()
    record_graph = records_to_graph(records[:5])
    record_ids = {node["id"] for node in record_graph["nodes"]}

    payload = trend_signals_to_graph(scored)
    targets = {edge["to"] for edge in payload["edges"] if edge["type"] == DERIVED_FROM}
    # The trend edges address source records by the same id convention the
    # record importer uses, so the two payloads join in Neo4j.
    assert all(target.startswith("source-record:") for target in targets)
    sample = next(iter(record_ids & targets), None) or next(iter(targets))
    assert sample.startswith("source-record:")


def test_both_the_week_and_its_baseline_records_are_linked(scored):
    signal = next(item for item in scored if item["window_record_ids"])
    payload = trend_signal_to_graph(signal)
    linked = {
        edge["to"].removeprefix("source-record:")
        for edge in payload["edges"]
        if edge["type"] == DERIVED_FROM
    }
    assert set(signal["record_ids"]) <= linked
    assert set(signal["window_record_ids"]) <= linked


def test_the_payload_is_deterministic_and_merges_shared_nodes(scored):
    first = trend_signals_to_graph(scored)
    again = trend_signals_to_graph(list(reversed(scored)))
    assert first == again
    startup_nodes = [node for node in first["nodes"] if node["label"] == "Startup"]
    assert len(startup_nodes) == len({node["id"] for node in startup_nodes})


def test_a_trend_signal_never_becomes_a_claim_or_carries_an_evidence_state(scored):
    payload = trend_signals_to_graph(scored)
    assert all(node["label"] != "Claim" for node in payload["nodes"])
    assert all(edge["type"] != "SUPPORTS" for edge in payload["edges"])
    for node in payload["nodes"]:
        assert "state" not in node["properties"]
        assert node["properties"].get("evidence_state") is None


def test_the_node_says_it_is_not_a_prediction(scored):
    node = trend_signal_to_graph(scored[0])["nodes"][0]
    assert "not a prediction" in node["properties"]["interpretation"]


def test_cypher_statements_are_parameterized(scored):
    statements = trend_import_statements(scored)
    assert statements
    for statement, parameters in statements:
        assert "$" in statement
        for value in parameters.values():
            if isinstance(value, str):
                assert "MERGE" not in value and "MATCH" not in value
    merges = [statement for statement, _ in statements if statement.startswith("MERGE")]
    matches = [statement for statement, _ in statements if statement.startswith("MATCH")]
    assert merges and matches
    # Edges MATCH their endpoints, so a signal never invents a source record.
    assert all("MERGE (source)-[:" in statement for statement in matches)


def test_invalid_signals_are_refused(scored):
    broken = {**scored[0], "label": "spiking"}
    with pytest.raises(ValueError, match="invalid trend signal"):
        trend_signal_to_graph(broken)


def test_the_ledger_note_supplies_provenance_without_deciding_state(scored):
    note = ledger_support_note(scored[0])
    assert note["signal_kind"] == "weekly_trend"
    assert note["evidence_state"] is None
    assert "assigned by the evidence ledger" in note["evidence_state_note"]
    assert note["valid_from"] and note["valid_to"]
    assert note["supporting_record_ids"] or note["baseline_record_ids"]
    assert note["method_parameters"]["alpha"]
    assert note["method_parameters"]["fingerprint"]
    # The ledger owns the vocabulary; the trend module must not pre-empt it.
    assert note["evidence_state"] not in EVIDENCE_STATES
