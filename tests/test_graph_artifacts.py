from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_neo4j_constraints_cover_graph_identity_and_time_indexes():
    text = (ROOT / "graph" / "constraints.cypher").read_text(encoding="utf-8")
    assert "source_record_id" in text
    assert "startup_company_id" in text
    assert "origin_cluster_id" in text
    assert "source_record_observed_at" in text
    assert "claim_id" in text


def test_shacl_shapes_cover_required_provenance_fields():
    text = (ROOT / "ontology" / "shapes.ttl").read_text(encoding="utf-8")
    for property_name in ("ts:recordId", "ts:sourceUrl", "ts:observedAt", "ts:contentHash", "ts:originClusterId"):
        assert property_name in text
    assert "ts:SourceRecordShape" in text
