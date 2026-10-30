from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_evidence_queries_cover_state_origin_and_temporal_review():
    text = (ROOT / "graph" / "evidence_queries.cypher").read_text(encoding="utf-8")
    assert "claim.state = $state" in text
    assert "count(DISTINCT record.origin_cluster_id)" in text
    assert "$observed_from" in text
    assert "$observed_to" in text
