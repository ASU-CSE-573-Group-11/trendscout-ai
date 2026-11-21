from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from graph.cypher import import_statements
from graph.evidence import evidence_to_graph


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
    parser.add_argument("records", type=Path, help="Validated records JSONL file")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "trendscout-dev"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE"))
    parser.add_argument("--no-constraints", action="store_true")
    parser.add_argument("--evidence", type=Path, help="Optional claim evidence JSONL file")
    args = parser.parse_args(argv)

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
