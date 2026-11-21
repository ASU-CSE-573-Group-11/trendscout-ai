import json
from pathlib import Path

from evaluation.real_graph_demo import run_demo, summarize


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "evaluation" / "mixed" / "real-graph-integration" / "graph.json"


def test_offline_demo_summarizes_real_graph_without_causal_inference():
    result = run_demo(GRAPH)
    summary = result["offline"]
    assert result["status"] == "offline_demo_complete"
    assert summary["node_count"] == 170
    assert summary["edge_count"] == 466
    assert summary["provenance_checks"] == {
        "claims_with_source_and_subject_paths": 45,
        "documented_domain_nodes": 45,
        "funding_rounds_without_reviewed_event_date": 3,
        "investor_to_specific_round_edges": 0,
    }


def test_company_demo_counts_observed_nodes_not_hires():
    summary = summarize(json.loads(GRAPH.read_text()))
    companies = {row["company_id"]: row for row in summary["companies"]}
    assert companies["langchain"]["funding_announcement_count"] == 1
    assert companies["langchain"]["observed_job_posting_count"] == 15
    assert companies["langchain"]["repository_count"] == 1
    assert companies["llamaindex"]["observed_job_posting_count"] == 3
    assert companies["browserbase"]["observed_job_posting_count"] == 0
    assert any("not completed hires" in limit for limit in summary["interpretation_limits"])
