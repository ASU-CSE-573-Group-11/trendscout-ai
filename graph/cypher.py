from __future__ import annotations

import re
from typing import Any, Iterable

from graph.import_contract import records_to_graph


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def build_import_payload(records: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build the parameter payload consumed by the Neo4j import statements."""
    graph = records_to_graph(records)
    return {
        "nodes": [
            {
                "id": node["id"],
                "label": node["label"],
                "properties": {**node["properties"], "id": node["id"]},
            }
            for node in graph["nodes"]
        ],
        "edges": graph["edges"],
    }


def import_statements(records: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Return parameterized Cypher statements without opening a database connection."""
    payload = build_import_payload(records)
    statements: list[tuple[str, dict[str, Any]]] = []
    for node in payload["nodes"]:
        label = node["label"]
        if not _IDENTIFIER.fullmatch(label):
            raise ValueError(f"unsafe graph label: {label}")
        statements.append(
            (
                f"MERGE (node:{label} {{id: $id}}) SET node += $properties",
                {"id": node["id"], "properties": node["properties"]},
            )
        )
    for edge in payload["edges"]:
        relation = edge["type"]
        if not _IDENTIFIER.fullmatch(relation):
            raise ValueError(f"unsafe relationship type: {relation}")
        statements.append(
            (
                f"MATCH (source {{id: $source_id}}), (target {{id: $target_id}}) "
                f"MERGE (source)-[:{relation}]->(target)",
                {
                    "source_id": edge["from"],
                    "target_id": edge["to"],
                },
            )
        )
    return statements
