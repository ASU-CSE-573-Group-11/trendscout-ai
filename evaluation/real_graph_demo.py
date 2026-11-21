from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.real_round import ROOT
from graph.import_contract import merge_graph_payloads


DEFAULT_GRAPH = ROOT / "evaluation" / "mixed" / "real-graph-integration" / "graph.json"
DEFAULT_OUTPUT = ROOT / "evaluation" / "mixed" / "real-graph-integration" / "demo-results.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return deterministic question-facing summaries from one graph payload."""
    payload = merge_graph_payloads(payload)
    nodes = {node["id"]: node for node in payload["nodes"]}
    outgoing: dict[tuple[str, str], set[str]] = defaultdict(set)
    incoming: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edge in payload["edges"]:
        outgoing[(edge["from"], edge["type"])].add(edge["to"])
        incoming[(edge["to"], edge["type"])].add(edge["from"])

    companies = []
    for startup in sorted(
        (node for node in payload["nodes"] if node["label"] == "Startup"),
        key=lambda node: node["properties"]["company_id"],
    ):
        startup_id = startup["id"]
        postings = outgoing[(startup_id, "HAS_JOB_POSTING")]
        repositories = outgoing[(startup_id, "HAS_REPOSITORY")]
        claims = incoming[(startup_id, "CLAIM_SUBJECT")]
        rounds = incoming[(startup_id, "FUNDING_OF")]
        investors = incoming[(startup_id, "BACKS")]
        skills = sorted(
            nodes[skill_id]["properties"]["name"]
            for posting_id in postings
            for skill_id in outgoing[(posting_id, "REQUIRES_SKILL")]
        )
        technologies = sorted(
            nodes[technology_id]["properties"]["name"]
            for posting_id in postings
            for technology_id in outgoing[(posting_id, "USES_TECHNOLOGY")]
        )
        companies.append(
            {
                "company_id": startup["properties"]["company_id"],
                "name": startup["properties"].get("name"),
                "claim_count": len(claims),
                "funding_announcement_count": len(rounds),
                "observed_job_posting_count": len(postings),
                "repository_count": len(repositories),
                "named_backer_count": len(investors),
                "skills": sorted(set(skills)),
                "technologies": sorted(set(technologies)),
            }
        )

    label_counts = Counter(node["label"] for node in payload["nodes"])
    edge_counts = Counter(edge["type"] for edge in payload["edges"])
    rounds = [node for node in payload["nodes"] if node["label"] == "FundingRound"]
    claim_paths = sum(
        bool(incoming[(claim["id"], "SUPPORTS")])
        and bool(outgoing[(claim["id"], "CLAIM_SUBJECT")])
        for claim in payload["nodes"]
        if claim["label"] == "Claim"
    )
    return {
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "node_labels": dict(sorted(label_counts.items())),
        "edge_types": dict(sorted(edge_counts.items())),
        "companies": companies,
        "provenance_checks": {
            "claims_with_source_and_subject_paths": claim_paths,
            "documented_domain_nodes": edge_counts["DOCUMENTS"],
            "funding_rounds_without_reviewed_event_date": sum(
                "event_at" not in node["properties"] for node in rounds
            ),
            "investor_to_specific_round_edges": edge_counts["PARTICIPATED_IN"],
        },
        "interpretation_limits": [
            "Observed job postings are not completed hires or headcount.",
            "Funding announcement observations do not establish causal hiring effects.",
            "Unknown funding event dates remain unknown.",
            "Source-excerpt claims are not independently adjudicated semantic gold.",
        ],
    }


def fetch_live_payload(
    expected: dict[str, list[dict[str, Any]]],
    *,
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read exactly the expected payload IDs and relationships from Neo4j."""
    from neo4j import GraphDatabase

    expected = merge_graph_payloads(expected)
    ids = [node["id"] for node in expected["nodes"]]
    edge_keys = [
        {"source": edge["from"], "type": edge["type"], "target": edge["to"]}
        for edge in expected["edges"]
    ]
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            node_rows = session.run(
                "MATCH (node) WHERE node.id IN $ids "
                "RETURN node.id AS id, labels(node)[0] AS label, properties(node) AS properties",
                ids=ids,
            )
            nodes = []
            for row in node_rows:
                properties = dict(row["properties"])
                properties.pop("id", None)
                nodes.append({"id": row["id"], "label": row["label"], "properties": properties})
            edge_rows = session.run(
                "UNWIND $edges AS edge "
                "MATCH (source {id: edge.source})-[relation]->(target {id: edge.target}) "
                "WHERE type(relation) = edge.type "
                "RETURN source.id AS source, type(relation) AS type, target.id AS target",
                edges=edge_keys,
            )
            edges = [
                {"from": row["source"], "type": row["type"], "to": row["target"]}
                for row in edge_rows
            ]
    finally:
        driver.close()
    return merge_graph_payloads({"nodes": nodes, "edges": edges})


def run_demo(
    graph_path: Path = DEFAULT_GRAPH,
    *,
    live: bool = False,
    uri: str = "bolt://localhost:7687",
    username: str = "neo4j",
    password: str = "trendscout-dev",
    database: str | None = None,
) -> dict[str, Any]:
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    offline = summarize(payload)
    result: dict[str, Any] = {
        "status": "offline_demo_complete",
        "graph": str(graph_path.relative_to(ROOT)),
        "graph_sha256": _sha(graph_path),
        "offline": offline,
        "live": None,
        "live_matches_offline": None,
        "scope": "Deterministic graph summaries; no hire, headcount, causal, or independent-gold claim.",
    }
    if live:
        live_payload = fetch_live_payload(
            payload,
            uri=uri,
            username=username,
            password=password,
            database=database,
        )
        live_summary = summarize(live_payload)
        result.update(
            {
                "status": "offline_and_live_demo_complete",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "live": live_summary,
                "live_matches_offline": live_summary == offline,
                "database": database or "neo4j",
                "uri": uri,
            }
        )
        if not result["live_matches_offline"]:
            raise ValueError("live Neo4j demo does not match the frozen offline graph")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "trendscout-dev"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE"))
    args = parser.parse_args()
    result = run_demo(
        args.graph,
        live=args.live,
        uri=args.uri,
        username=args.username,
        password=args.password,
        database=args.database,
    )
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}))


if __name__ == "__main__":
    main()
