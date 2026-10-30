from collectors.records import make_record
from graph.rdf import TS
from graph.shacl import validate_graph, validate_records
from rdflib import Graph, RDF


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


def test_valid_source_record_conforms_to_shacl():
    conforms, _, report = validate_records([_record()])
    assert conforms is True
    assert "conforms" in report.lower()


def test_invalid_rdf_graph_fails_shacl():
    graph = Graph()
    source = TS["source-record/example"]
    graph.add((source, RDF.type, TS.SourceRecord))
    conforms, _, report = validate_graph(graph)
    assert conforms is False
    assert "recordid" in report.lower()
