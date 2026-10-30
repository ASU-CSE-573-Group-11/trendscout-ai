import pytest

from collectors.records import make_record
from graph.evidence import evidence_json, evidence_to_graph, make_evidence_entry


def _record():
    return make_record(
        source_type="news",
        source_url="https://example.com/story",
        title="LangChain evaluation",
        text="LangChain published a public evaluation announcement.",
        publisher="Example News",
        company_id="langchain",
        startup_name="LangChain",
        event_at="2026-10-29T00:00:00Z",
        published_at="2026-10-30T00:00:00Z",
    )


def test_evidence_keeps_source_provenance_and_three_clocks():
    entry = make_evidence_entry(
        _record(),
        claim_text="LangChain published an evaluation announcement.",
    )
    assert entry["record_id"]
    assert entry["origin_cluster_id"]
    assert entry["event_at"] == "2026-10-29T00:00:00Z"
    assert entry["published_at"] == "2026-10-30T00:00:00Z"
    assert entry["observed_at"]


def test_evidence_graph_links_source_record_to_claim():
    entry = make_evidence_entry(_record(), claim_text="A supported claim.")
    graph = evidence_to_graph(entry)
    assert graph["edges"] == [
        {
            "from": f"source-record:{entry['record_id']}",
            "type": "SUPPORTS",
            "to": entry["claim_id"],
        }
    ]
    assert evidence_json(entry).startswith('{"claim_id"')


def test_evidence_rejects_invalid_state_and_confidence():
    with pytest.raises(ValueError, match="unsupported evidence state"):
        make_evidence_entry(_record(), claim_text="Claim.", state="proven")
    with pytest.raises(ValueError, match="between 0 and 1"):
        make_evidence_entry(_record(), claim_text="Claim.", confidence=1.1)
