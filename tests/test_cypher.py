from graph.cypher import build_import_payload, import_statements
from graph.neo4j import split_cypher
from collectors.records import make_record


def test_split_cypher_ignores_comments_and_blank_statements():
    statements = split_cypher(
        "// comment\nCREATE CONSTRAINT test IF NOT EXISTS\nFOR (n:Test)\nREQUIRE n.id IS UNIQUE;\n\n"
    )
    assert len(statements) == 1
    assert "CREATE CONSTRAINT test" in statements[0]


def test_constraints_include_claim_identity():
    from pathlib import Path

    text = Path("graph/constraints.cypher").read_text(encoding="utf-8")
    assert "claim_id" in text


def test_import_payload_keeps_graph_ids_in_node_properties():
    record = make_record(
        source_type="news",
        source_url="https://example.com/story",
        title="LangChain evaluation",
        text="A public evaluation announcement.",
        publisher="Example News",
        company_id="langchain",
        startup_name="LangChain",
        published_at="2026-10-30T00:00:00Z",
    )
    payload = build_import_payload([record])
    source = next(node for node in payload["nodes"] if node["label"] == "SourceRecord")
    assert source["properties"]["id"] == source["id"]
    assert payload["edges"]


def test_import_statements_are_parameterized_and_deterministic():
    record = make_record(
        source_type="reference",
        source_url="https://example.com/identity",
        title="Identity",
        text="Identity record.",
        publisher="Example",
        company_id="langchain",
        startup_name="LangChain",
    )
    first = import_statements([record])
    second = import_statements([record])
    assert first == second
    assert first[0][0].startswith("MERGE (node:")
    assert first[-1][0].startswith("MATCH (source")
    assert first[0][1]["properties"]
    assert first[-1][1]["source_id"]
