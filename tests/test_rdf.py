from rdflib import RDF, XSD

from collectors.records import make_record
from graph.rdf import TS, graph_to_rdf, serialize_rdf


def test_rdf_export_preserves_provenance_relationships_and_time():
    record = make_record(
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
    graph = graph_to_rdf([record])
    source = next(graph.subjects(RDF.type, TS.SourceRecord))
    startup = next(graph.subjects(RDF.type, TS.Startup))
    assert (source, TS.about, startup) in graph
    assert graph.value(source, TS.observedAt).datatype == XSD.dateTime
    assert graph.value(source, TS.sourceUrl).datatype == XSD.anyURI


def test_rdf_serialization_is_turtle():
    record = make_record(
        source_type="reference",
        source_url="https://example.com/identity",
        title="Identity",
        text="Identity record.",
        publisher="Example",
        company_id="langchain",
        startup_name="LangChain",
    )
    turtle = serialize_rdf([record])
    assert "@prefix ts:" in turtle
    assert "SourceRecord" in turtle
