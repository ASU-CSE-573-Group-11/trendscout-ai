from __future__ import annotations

import re
from typing import Any, Iterable

from collectors.records import validate_record


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise ValueError("cannot create an empty graph identifier")
    return slug


def merge_graph_payloads(*payloads: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Merge deterministic graph payloads and reject conflicting or dangling data."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    for payload in payloads:
        if set(payload) != {"nodes", "edges"}:
            raise ValueError("graph payload must contain exactly nodes and edges")
        for node in payload["nodes"]:
            if set(node) != {"id", "label", "properties"}:
                raise ValueError("graph node must contain id, label, and properties")
            if not node["id"] or not node["label"] or not isinstance(node["properties"], dict):
                raise ValueError("graph node id, label, and properties must be valid")
            existing = nodes.get(node["id"])
            if existing is not None and existing != node:
                raise ValueError(f"conflicting graph node properties for {node['id']}")
            nodes[node["id"]] = node
        for edge in payload["edges"]:
            if set(edge) != {"from", "type", "to"}:
                raise ValueError("graph edge must contain from, type, and to")
            edges.add((edge["from"], edge["type"], edge["to"]))
    dangling = sorted(
        (source, relation, target)
        for source, relation, target in edges
        if source not in nodes or target not in nodes
    )
    if dangling:
        raise ValueError(f"graph payload contains dangling edges: {dangling[:3]}")
    return {
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": [
            {"from": source, "type": relation, "to": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _node(node_id: str, label: str, **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "label": label, "properties": properties}


def record_to_graph(record: dict[str, Any]) -> dict[str, Any]:
    """Convert one validated source record into graph-ready nodes and edges."""
    errors = validate_record(record)
    if errors:
        raise ValueError(f"cannot import invalid record {record.get('record_id')}: {errors}")

    record_id = record["record_id"]
    source_node = f"source-record:{record_id}"
    nodes = [
        _node(
            source_node,
            "SourceRecord",
            record_id=record_id,
            source_type=record["source_type"],
            source_url=record["source_url"],
            title=record.get("title"),
            passage=record.get("text"),
            event_at=record.get("event_at"),
            published_at=record.get("published_at"),
            observed_at=record["observed_at"],
            content_hash=record["content_hash"],
            origin_cluster_id=record["origin_cluster_id"],
            collector_version=record["collector_version"],
        )
    ]
    edges: list[dict[str, str]] = []

    company_id = record.get("company_id")
    if company_id:
        company_node = f"startup:{company_id}"
        nodes.append(_node(company_node, "Startup", company_id=company_id, name=record.get("startup_name")))
        edges.append({"from": source_node, "type": "ABOUT", "to": company_node})

    publisher = record.get("publisher")
    if publisher:
        # Slugify so RDF URIs remain valid for names like "Weights & Biases".
        publisher_node = f"publisher:{_slug(publisher)}"
        nodes.append(_node(publisher_node, "Publisher", name=publisher))
        edges.append({"from": source_node, "type": "PUBLISHED_BY", "to": publisher_node})

    origin_node = f"origin:{record['origin_cluster_id']}"
    nodes.append(_node(origin_node, "OriginCluster", origin_cluster_id=record["origin_cluster_id"]))
    edges.append({"from": source_node, "type": "MEMBER_OF_ORIGIN", "to": origin_node})

    return {"nodes": nodes, "edges": edges}


def records_to_graph(records: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build a deterministic graph payload, merging shared nodes and edges."""
    return merge_graph_payloads(*(record_to_graph(record) for record in records))
