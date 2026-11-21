from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from graph.cypher import graph_import_statements, import_statements
from graph.evidence import evidence_to_graph
from graph.import_contract import merge_graph_payloads


def split_cypher(script: str) -> list[str]:
    """Split a Cypher script into statements, ignoring comments and blanks."""
    statements: list[str] = []
    for raw in script.split(";"):
        statement = "\n".join(
            line for line in raw.splitlines() if line.strip() and not line.lstrip().startswith("//")
        ).strip()
        if statement:
            statements.append(statement)
    return statements


def load_records(
    records: Iterable[dict],
    *,
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
    apply_constraints: bool = True,
    evidence_entries: Iterable[dict] | None = None,
) -> dict:
    """Load source records and their graph projections into a Neo4j database."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError(
            "The Neo4j driver is missing. Install requirements-interface.txt."
        ) from exc

    records = list(records)
    statements = import_statements(records)
    evidence_entries = list(evidence_entries or [])
    for entry in evidence_entries:
        payload = evidence_to_graph(entry)
        for node in payload["nodes"]:
            statements.append(
                (
                    "MERGE (node:Claim {id: $id}) SET node += $properties",
                    {
                        "id": node["id"],
                        "properties": {
                            **node["properties"],
                            "id": node["id"],
                            "claim_id": node["id"],
                        },
                    },
                )
            )
        for edge in payload["edges"]:
            statements.append(
                (
                    "MATCH (source {id: $source_id}), (target {id: $target_id}) "
                    "MERGE (source)-[:SUPPORTS]->(target)",
                    {
                        "source_id": f"source-record:{edge['from'].split(':', 1)[1]}",
                        "target_id": edge["to"],
                    },
                )
            )
    constraints_path = Path(__file__).with_name("constraints.cypher")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            session.run("RETURN 1").consume()

            if apply_constraints:
                for statement in split_cypher(constraints_path.read_text(encoding="utf-8")):
                    session.run(statement).consume()

            for query, parameters in statements:
                session.run(query, parameters).consume()

            count = session.run(
                "MATCH (record:SourceRecord) RETURN count(record) AS count"
            ).single()["count"]
    finally:
        driver.close()

    return {
        "status": "success",
        "record_count": len(records),
        "source_record_nodes": count,
        "database": database or "neo4j",
        "uri": uri,
    }


def load_graph_payload(
    payload: dict,
    *,
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
    apply_constraints: bool = True,
) -> dict:
    """Load a complete validated semantic graph payload into Neo4j."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError(
            "The Neo4j driver is missing. Install requirements-interface.txt."
        ) from exc

    payload = merge_graph_payloads(payload)
    statements = graph_import_statements(payload)
    constraints_path = Path(__file__).with_name("constraints.cypher")
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            session.run("RETURN 1").consume()
            if apply_constraints:
                for statement in split_cypher(constraints_path.read_text(encoding="utf-8")):
                    session.run(statement).consume()
            for query, parameters in statements:
                session.run(query, parameters).consume()
            rows = session.run(
                "MATCH (node) UNWIND labels(node) AS label "
                "RETURN label, count(node) AS count ORDER BY label"
            )
            label_counts = {row["label"]: row["count"] for row in rows}
            payload_node_matches = session.run(
                "MATCH (node) WHERE node.id IN $ids RETURN count(node) AS count",
                ids=[node["id"] for node in payload["nodes"]],
            ).single()["count"]
            payload_edge_matches = session.run(
                "UNWIND $edges AS edge "
                "MATCH (source {id: edge.source})-[relation]->(target {id: edge.target}) "
                "WHERE type(relation) = edge.type RETURN count(relation) AS count",
                edges=[
                    {
                        "source": edge["from"],
                        "type": edge["type"],
                        "target": edge["to"],
                    }
                    for edge in payload["edges"]
                ],
            ).single()["count"]
    finally:
        driver.close()
    return {
        "status": "success",
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "database_label_counts": label_counts,
        "payload_node_matches": payload_node_matches,
        "payload_edge_matches": payload_edge_matches,
        "payload_verified": payload_node_matches == len(payload["nodes"])
        and payload_edge_matches == len(payload["edges"]),
        "database": database or "neo4j",
        "uri": uri,
    }


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(value)
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load TrendScout records into Neo4j.")
    parser.add_argument("records", type=Path, nargs="?", help="Validated records JSONL file")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "trendscout-dev"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE"))
    parser.add_argument("--no-constraints", action="store_true")
    parser.add_argument("--evidence", type=Path, help="Optional claim evidence JSONL file")
    parser.add_argument("--graph-payload", type=Path, help="Complete semantic graph JSON payload")
    args = parser.parse_args(argv)

    if args.graph_payload:
        if args.records or args.evidence:
            parser.error("--graph-payload cannot be combined with records or --evidence")
        result = load_graph_payload(
            json.loads(args.graph_payload.read_text(encoding="utf-8")),
            uri=args.uri,
            username=args.username,
            password=args.password,
            database=args.database,
            apply_constraints=not args.no_constraints,
        )
    else:
        if args.records is None:
            parser.error("records or --graph-payload is required")
        result = load_records(
            load_jsonl(args.records),
            uri=args.uri,
            username=args.username,
            password=args.password,
            database=args.database,
            apply_constraints=not args.no_constraints,
            evidence_entries=load_jsonl(args.evidence) if args.evidence else None,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
