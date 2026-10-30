from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_temporal_queries_require_company_window_and_origin_threshold():
    text = (ROOT / "graph" / "temporal_queries.cypher").read_text(encoding="utf-8")
    assert "SourceRecord" in text
    assert "Claim" in text
    assert "$company_id" in text
    assert "$observed_from" in text
    assert "$observed_to" in text
    assert "$minimum_independent_origins" in text
    assert "count(DISTINCT" in text or "collect(DISTINCT" in text
