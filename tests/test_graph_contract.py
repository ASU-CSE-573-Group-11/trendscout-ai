from graph.import_contract import record_to_graph, records_to_graph
from collectors.records import make_record


def _record(**kwargs):
    return make_record(
        source_type="news",
        source_url=kwargs.pop("source_url", "https://example.com/story"),
        title="LangChain announces a new evaluation tool",
        text="LangChain published a public announcement about evaluation.",
        publisher="Example News",
        company_id="langchain",
        startup_name="LangChain",
        published_at="2026-10-30T00:00:00Z",
        **kwargs,
    )


def test_record_to_graph_preserves_provenance_and_time():
    record = _record(event_at="2026-10-29T00:00:00Z")
    payload = record_to_graph(record)
    source = next(node for node in payload["nodes"] if node["label"] == "SourceRecord")
    assert source["properties"]["origin_cluster_id"] == record["origin_cluster_id"]
    assert source["properties"]["event_at"] == "2026-10-29T00:00:00Z"
    assert {"from": source["id"], "type": "ABOUT", "to": "startup:langchain"} in payload["edges"]


def test_records_to_graph_merges_shared_company_and_origin_nodes():
    first = _record()
    second = _record(source_url="https://example.com/other-story")
    payload = records_to_graph([first, second])
    assert sum(node["label"] == "Startup" for node in payload["nodes"]) == 1
    assert sum(node["label"] == "Publisher" for node in payload["nodes"]) == 1
    assert len([edge for edge in payload["edges"] if edge["type"] == "PUBLISHED_BY"]) == 2
    assert len([edge for edge in payload["edges"] if edge["type"] == "ABOUT"]) == 2
