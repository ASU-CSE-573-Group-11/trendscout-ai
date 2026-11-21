"""Graph retrieval with a backend that works without a running database.

The graph payload is built by **Mehmet's** ``graph.import_contract.records_to_graph``
and by ``signals.graph_export.trend_signals_to_graph``; neither is reimplemented
here. :class:`InMemoryGraph` then answers the competency queries over that
payload in Python.

Why an in-memory backend exists
-------------------------------
``evaluation/questions.seed.json`` requires the demo to replay a frozen snapshot
even when a live source is down, and a Neo4j instance is exactly such a
dependency. The in-memory backend answers the subset of competency queries the
interface needs, over the same nodes and edges Neo4j would hold.

It is an *equivalent*, not the real thing, and every answer says which backend
produced it. The selected Cypher from ``graph/*.cypher`` still travels with the
answer, so a reviewer can see the query the result corresponds to.
:class:`Neo4jBackend` executes those templates for real when the driver and a
database are available; it is written against the official driver API and has
not been run against a live instance yet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from graph.import_contract import records_to_graph
from retrieval.graph_queries import CypherLibrary, CypherTemplate
from signals.graph_export import trend_signals_to_graph


@dataclass(frozen=True)
class GraphPath:
    """One evidence path, structured and renderable."""

    steps: tuple[dict[str, str], ...]
    nodes: tuple[dict[str, Any], ...]

    def render(self) -> str:
        """A single-line path for the citations panel.

        Edge direction is shown as stored. Evidence paths are not directed
        chains -- a record points at both its startup and its claim -- so steps
        that do not continue the previous one start a new segment after ``;``
        rather than being silently reversed into a chain that does not exist.
        """
        segments: list[str] = []
        current: list[str] = []
        for step in self.steps:
            if current and current[-1] == step["from"]:
                current.extend([f"-[{step['type']}]->", step["to"]])
            else:
                if current:
                    segments.append(" ".join(current))
                current = [step["from"], f"-[{step['type']}]->", step["to"]]
        if current:
            segments.append(" ".join(current))
        return " ; ".join(segments)

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": [dict(step) for step in self.steps],
            "nodes": [dict(node) for node in self.nodes],
            "rendered": self.render(),
        }


@dataclass
class GraphResult:
    """The outcome of one graph query, with the query that produced it."""

    purpose: str
    template: CypherTemplate | None
    parameters: dict[str, Any]
    rows: list[dict[str, Any]] = field(default_factory=list)
    paths: list[GraphPath] = field(default_factory=list)
    backend: str = "in_memory"
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "cypher": self.template.query if self.template else None,
            "cypher_name": self.template.name if self.template else None,
            "parameters": dict(self.parameters),
            "rows": list(self.rows),
            "paths": [path.as_dict() for path in self.paths],
            "backend": self.backend,
            "note": self.note,
        }


class GraphBackend(Protocol):
    """What the interface needs from a graph store."""

    name: str

    def company_records(self, company_id: str, *, observed_from: str | None = None, observed_to: str | None = None) -> GraphResult: ...

    def independent_origins(self, company_id: str) -> GraphResult: ...

    def temporal_paths(self, company_id: str, *, observed_from: str, observed_to: str) -> GraphResult: ...

    def trend_paths(self, company_id: str, *, metric: str | None = None, weeks: Sequence[str] | None = None) -> GraphResult: ...


@dataclass
class InMemoryGraph:
    """The competency queries, answered over the shared graph payload."""

    nodes: dict[str, dict[str, Any]]
    edges: list[dict[str, str]]
    library: CypherLibrary = field(default_factory=CypherLibrary)
    name: str = "in_memory"

    def __post_init__(self) -> None:
        self._out: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._in: dict[str, list[dict[str, str]]] = defaultdict(list)
        for edge in self.edges:
            self._out[edge["from"]].append(edge)
            self._in[edge["to"]].append(edge)

    # -- construction ----------------------------------------------------

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        trend_signals: Iterable[Mapping[str, Any]] | None = None,
        cohort: Mapping[str, Any] | None = None,
        library: CypherLibrary | None = None,
    ) -> "InMemoryGraph":
        records = list(records)
        # Repeated snapshots repeat a record verbatim; merge by record_id so one
        # piece of evidence is one node, exactly as MERGE would do in Neo4j.
        unique = {record["record_id"]: record for record in records}
        payload = records_to_graph(list(unique.values()))
        nodes = {node["id"]: node for node in payload["nodes"]}
        edges = list(payload["edges"])
        if trend_signals:
            trend_payload = trend_signals_to_graph(list(trend_signals))
            for node in trend_payload["nodes"]:
                nodes.setdefault(node["id"], node)
            seen = {(edge["from"], edge["type"], edge["to"]) for edge in edges}
            for edge in trend_payload["edges"]:
                key = (edge["from"], edge["type"], edge["to"])
                if key not in seen and edge["to"] in nodes:
                    # Edges whose endpoint was not loaded are dropped, matching
                    # the MATCH-based import: a signal never invents a record.
                    seen.add(key)
                    edges.append(edge)

        # Sectors come from the frozen cohort's own `category` field, which is
        # already the project's sector vocabulary. The proposal lists Sector and
        # OPERATES_IN as core ontology types, so this materialises something the
        # design specifies rather than inventing a grouping. Nothing in graph/
        # changes: these nodes are built here, alongside the trend signals.
        for company in (cohort or {}).get("companies", []):
            company_id, category = company.get("company_id"), company.get("category")
            if not company_id or not category:
                continue
            startup_node = f"startup:{company_id}"
            if startup_node not in nodes:
                # Only sector-tag companies the snapshot actually has records
                # for; a cohort entry with no evidence is not in this graph.
                continue
            sector_node = f"sector:{category}"
            nodes.setdefault(
                sector_node,
                {
                    "id": sector_node,
                    "label": "Sector",
                    "properties": {"sector_id": category, "name": category.replace("_", " ")},
                },
            )
            edges.append({"from": startup_node, "type": "OPERATES_IN", "to": sector_node})

        unique_edges = {(edge["from"], edge["type"], edge["to"]) for edge in edges}
        edges = [
            {"from": source, "type": relation, "to": target}
            for source, relation, target in sorted(unique_edges)
        ]
        return cls(nodes=nodes, edges=edges, library=library or CypherLibrary())

    # -- helpers ---------------------------------------------------------

    def node(self, node_id: str) -> dict[str, Any] | None:
        return self.nodes.get(node_id)

    def _records_about(self, company_id: str) -> list[dict[str, Any]]:
        target = f"startup:{company_id}"
        found = []
        for edge in self._in.get(target, []):
            if edge["type"] != "ABOUT":
                continue
            node = self.nodes.get(edge["from"])
            if node and node["label"] == "SourceRecord":
                found.append(node)
        return found

    @staticmethod
    def _in_window(node: Mapping[str, Any], observed_from: str | None, observed_to: str | None) -> bool:
        observed_at = node["properties"].get("observed_at")
        if not observed_at:
            return False
        if observed_from and observed_at < observed_from:
            return False
        if observed_to and observed_at >= observed_to:
            return False
        return True

    def companies(self) -> list[str]:
        return sorted(
            node["properties"]["company_id"]
            for node in self.nodes.values()
            if node["label"] == "Startup" and node["properties"].get("company_id")
        )

    # -- queries ---------------------------------------------------------

    def company_records(
        self, company_id: str, *, observed_from: str | None = None, observed_to: str | None = None
    ) -> GraphResult:
        purpose = "records_in_window" if observed_from else "company_records"
        template = self.library.for_purpose(purpose)
        selected = [
            node
            for node in self._records_about(company_id)
            if observed_from is None or self._in_window(node, observed_from, observed_to)
        ]
        selected.sort(key=lambda node: node["properties"].get("observed_at") or "", reverse=True)
        rows = [
            {
                "company_id": company_id,
                "record_id": node["properties"]["record_id"],
                "source_type": node["properties"].get("source_type"),
                "source_url": node["properties"].get("source_url"),
                "title": node["properties"].get("title"),
                "observed_at": node["properties"].get("observed_at"),
                "published_at": node["properties"].get("published_at"),
                "event_at": node["properties"].get("event_at"),
                "origin_cluster_id": node["properties"].get("origin_cluster_id"),
            }
            for node in selected
        ]
        return GraphResult(
            purpose=purpose,
            template=template,
            parameters={
                key: value
                for key, value in (
                    ("company_id", company_id),
                    ("observed_from", observed_from),
                    ("observed_to", observed_to),
                )
                if value is not None
            },
            rows=rows,
            backend=self.name,
        )

    def independent_origins(self, company_id: str) -> GraphResult:
        origins = sorted(
            {
                node["properties"].get("origin_cluster_id")
                for node in self._records_about(company_id)
                if node["properties"].get("origin_cluster_id")
            }
        )
        return GraphResult(
            purpose="independent_origins",
            template=self.library.for_purpose("independent_origins"),
            parameters={"company_id": company_id},
            rows=[
                {
                    "company_id": company_id,
                    "independent_origins": len(origins),
                    "origin_cluster_ids": origins,
                }
            ],
            backend=self.name,
        )

    def _paths_from_records(
        self, company_id: str, records: Sequence[Mapping[str, Any]], relation: str, target_label: str
    ) -> list[GraphPath]:
        startup = f"startup:{company_id}"
        paths: list[GraphPath] = []
        for record in records:
            record_id = record["id"]
            for edge in self._in.get(record_id, []) + self._out.get(record_id, []):
                if edge["type"] != relation:
                    continue
                other = edge["to"] if edge["from"] == record_id else edge["from"]
                node = self.nodes.get(other)
                if not node or node["label"] != target_label:
                    continue
                # Both edges are stored as they exist: the record points at its
                # startup and at the attached claim. Reversing either one to
                # force a single chain would misreport the graph.
                steps = (
                    {"from": record_id, "type": "ABOUT", "to": startup},
                    (
                        {"from": record_id, "type": relation, "to": other}
                        if edge["from"] == record_id
                        else {"from": other, "type": relation, "to": record_id}
                    ),
                )
                paths.append(
                    GraphPath(
                        steps=steps,
                        nodes=tuple(
                            dict(item)
                            for item in (self.nodes.get(startup) or {}, record, node)
                            if item
                        ),
                    )
                )
        return paths

    def temporal_paths(
        self, company_id: str, *, observed_from: str, observed_to: str
    ) -> GraphResult:
        template = self.library.for_purpose("temporal_multihop")
        records = [
            node
            for node in self._records_about(company_id)
            if self._in_window(node, observed_from, observed_to)
        ]
        records.sort(key=lambda node: node["properties"].get("observed_at") or "")
        paths = self._paths_from_records(company_id, records, "SUPPORTS", "Claim")
        paths.extend(self._paths_from_records(company_id, records, "DERIVED_FROM", "TrendSignal"))
        note = None
        if not paths and records:
            note = (
                "records exist in the window but no claim or trend signal is attached to them; "
                "the evidence ledger has not extracted claims for this company yet"
            )
        return GraphResult(
            purpose="temporal_multihop",
            template=template,
            parameters={
                "company_id": company_id,
                "observed_from": observed_from,
                "observed_to": observed_to,
            },
            rows=[
                {
                    "company_id": company_id,
                    "records_in_window": len(records),
                    "paths": len(paths),
                }
            ],
            paths=paths,
            backend=self.name,
            note=note,
        )

    def trend_paths(
        self,
        company_id: str,
        *,
        metric: str | None = None,
        weeks: Sequence[str] | None = None,
    ) -> GraphResult:
        """Trend signals about a company, with their DERIVED_FROM evidence."""
        wanted_weeks = set(weeks) if weeks else None
        startup = f"startup:{company_id}"
        signals = []
        for edge in self._in.get(startup, []):
            if edge["type"] != "ABOUT":
                continue
            node = self.nodes.get(edge["from"])
            if not node or node["label"] != "TrendSignal":
                continue
            properties = node["properties"]
            if metric and properties.get("metric") != metric:
                continue
            if wanted_weeks is not None and properties.get("iso_week") not in wanted_weeks:
                continue
            signals.append(node)
        signals.sort(key=lambda node: (node["properties"].get("iso_week") or "", node["id"]))

        paths: list[GraphPath] = []
        rows: list[dict[str, Any]] = []
        for node in signals:
            evidence = [
                edge["to"]
                for edge in self._out.get(node["id"], [])
                if edge["type"] == "DERIVED_FROM"
            ]
            rows.append(
                {
                    "company_id": company_id,
                    "trend_id": node["id"],
                    "metric": node["properties"].get("metric"),
                    "iso_week": node["properties"].get("iso_week"),
                    "label": node["properties"].get("label"),
                    "trend_score": node["properties"].get("trend_score"),
                    "value": node["properties"].get("value"),
                    "supporting_records": len(evidence),
                }
            )
            for record_id in evidence[:3]:
                record_node = self.nodes.get(record_id)
                if not record_node:
                    continue
                paths.append(
                    GraphPath(
                        steps=(
                            {"from": node["id"], "type": "DERIVED_FROM", "to": record_id},
                            {"from": node["id"], "type": "ABOUT", "to": startup},
                        ),
                        nodes=(self.nodes.get(startup) or {}, node, record_node),
                    )
                )
        return GraphResult(
            purpose="trend_signals",
            template=self.library.for_purpose("temporal_multihop"),
            parameters={"company_id": company_id, "metric": metric, "weeks": list(weeks or [])},
            rows=rows,
            paths=paths,
            backend=self.name,
            note=(
                None
                if signals
                else "no trend signal is attached to this company in the requested window"
            ),
        )

    def sectors(self) -> list[str]:
        return sorted(
            node["properties"]["sector_id"]
            for node in self.nodes.values()
            if node["label"] == "Sector"
        )

    def companies_in_sector(self, sector_id: str) -> list[str]:
        target = f"sector:{sector_id}"
        found = []
        for edge in self._in.get(target, []):
            if edge["type"] != "OPERATES_IN":
                continue
            node = self.nodes.get(edge["from"])
            if node and node["label"] == "Startup":
                found.append(node["properties"]["company_id"])
        return sorted(found)

    def sector_attention(
        self,
        *,
        observed_from: str | None = None,
        observed_to: str | None = None,
        minimum_voice_origins: int = 2,
        voice_types: Sequence[str] = ("public_voice", "news"),
    ) -> GraphResult:
        """Attention and operational signals per sector, for the third prototype question.

        A sector qualifies when independent *origins* carrying public-voice or
        news coverage reach the minimum, and at least one company in it also
        produced an operational signal in the same window. Origins are counted,
        not articles, because syndicated copies of one origin are not several
        voices.
        """
        rows: list[dict[str, Any]] = []
        voice_set, operational_set = set(voice_types), {"github", "job"}
        for sector_id in self.sectors():
            companies = self.companies_in_sector(sector_id)
            voice_origins: set[str] = set()
            operational_records: list[str] = []
            record_ids: list[str] = []
            for company_id in companies:
                for node in self._records_about(company_id):
                    if observed_from and not self._in_window(node, observed_from, observed_to):
                        continue
                    properties = node["properties"]
                    source_type = properties.get("source_type")
                    if source_type in voice_set and properties.get("origin_cluster_id"):
                        voice_origins.add(properties["origin_cluster_id"])
                        record_ids.append(properties["record_id"])
                    elif source_type in operational_set:
                        operational_records.append(properties["record_id"])
            rows.append(
                {
                    "sector_id": sector_id,
                    "companies": companies,
                    "independent_voice_origins": len(voice_origins),
                    "voice_origin_ids": sorted(voice_origins),
                    "operational_records": len(operational_records),
                    "qualifies": len(voice_origins) >= minimum_voice_origins
                    and bool(operational_records),
                    "record_ids": sorted(record_ids),
                }
            )
        rows.sort(key=lambda row: (-row["independent_voice_origins"], row["sector_id"]))
        return GraphResult(
            purpose="sector_attention",
            template=self.library.for_purpose("independent_origins"),
            parameters={
                "observed_from": observed_from,
                "observed_to": observed_to,
                "minimum_independent_origins": minimum_voice_origins,
            },
            rows=rows,
            backend=self.name,
            note=(
                None
                if rows
                else "no Sector nodes in this graph; pass the frozen cohort to from_records"
            ),
        )

    def describe(self) -> dict[str, Any]:
        labels: dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            labels[node["label"]] += 1
        relations: dict[str, int] = defaultdict(int)
        for edge in self.edges:
            relations[edge["type"]] += 1
        return {
            "backend": self.name,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "labels": dict(sorted(labels.items())),
            "relations": dict(sorted(relations.items())),
            "cypher": self.library.describe(),
            "caveat": (
                "answers the competency queries in Python over the same nodes and edges Neo4j "
                "would hold; the selected Cypher is reported but not executed"
            ),
        }


@dataclass
class Neo4jBackend:
    """Execute the real Cypher templates against Neo4j.

    Written against the official ``neo4j`` driver. The live Community Edition
    loader and backend smoke test have passed; the interface may still default
    to :class:`InMemoryGraph`.
    """

    uri: str
    username: str
    password: str
    database: str | None = None
    library: CypherLibrary = field(default_factory=CypherLibrary)
    name: str = "neo4j"

    def __post_init__(self) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - optional path
            raise RuntimeError(
                "the neo4j driver is not installed; install requirements-interface.txt or use "
                "the in-memory graph backend"
            ) from exc
        self._driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))

    def close(self) -> None:  # pragma: no cover - optional path
        self._driver.close()

    def _run(self, purpose: str, parameters: Mapping[str, Any]) -> GraphResult:  # pragma: no cover
        template = self.library.for_purpose(purpose)
        if template is None:
            return GraphResult(
                purpose=purpose,
                template=None,
                parameters=dict(parameters),
                backend=self.name,
                note=f"no Cypher template matches purpose {purpose!r}",
            )
        query = template.query.rstrip().rstrip(";")
        with self._driver.session(database=self.database) as session:
            records = session.run(query, **template.bind(parameters))
            rows = [dict(record) for record in records]
        return GraphResult(
            purpose=purpose,
            template=template,
            parameters=template.bind(parameters),
            rows=rows,
            backend=self.name,
        )

    def company_records(  # pragma: no cover - optional path
        self, company_id: str, *, observed_from: str | None = None, observed_to: str | None = None
    ) -> GraphResult:
        if observed_from and observed_to:
            return self._run(
                "records_in_window", {"observed_from": observed_from, "observed_to": observed_to}
            )
        return self._run("company_records", {"company_id": company_id})

    def independent_origins(self, company_id: str) -> GraphResult:  # pragma: no cover
        return self._run("independent_origins", {"company_id": company_id})

    def temporal_paths(  # pragma: no cover - optional path
        self, company_id: str, *, observed_from: str, observed_to: str
    ) -> GraphResult:
        return self._run(
            "temporal_multihop",
            {"company_id": company_id, "observed_from": observed_from, "observed_to": observed_to},
        )

    def trend_paths(  # pragma: no cover - optional path
        self, company_id: str, *, metric: str | None = None, weeks: Sequence[str] | None = None
    ) -> GraphResult:
        return self._run("latest_state_path", {"company_id": company_id})


__all__ = [
    "GraphBackend",
    "GraphPath",
    "GraphResult",
    "InMemoryGraph",
    "Neo4jBackend",
]
