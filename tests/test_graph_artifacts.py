from pathlib import Path

from rdflib import Graph, OWL, RDF, RDFS

from graph.rdf import TS


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


def test_ontology_declares_research_classes_and_property_contracts():
    graph = Graph().parse(ROOT / "ontology" / "trendscout.ttl", format="turtle")
    classes = {
        TS.Startup,
        TS.Investor,
        TS.Voice,
        TS.Product,
        TS.Technology,
        TS.Skill,
        TS.JobPosting,
        TS.Repository,
        TS.FundingRound,
    }
    assert all((term, RDF.type, OWL.Class) in graph for term in classes)

    properties = set(graph.subjects(RDF.type, OWL.ObjectProperty)) | set(
        graph.subjects(RDF.type, OWL.DatatypeProperty)
    )
    assert properties
    for property_iri in properties:
        assert graph.value(property_iri, RDFS.domain) is not None
        assert graph.value(property_iri, RDFS.range) is not None
