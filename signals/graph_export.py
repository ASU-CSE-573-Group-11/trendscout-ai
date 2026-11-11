"""Project trend signals into the graph payload shape Mehmet's loader uses.

Why this lives here
-------------------
``graph/import_contract.py`` converts *source records* into nodes and edges, and
``graph/cypher.py`` turns that payload into parameterized statements. A trend
signal is neither a source record nor a claim, so rather than modify either
module this one emits the same payload shape -- ``{"id", "label",
"properties"}`` nodes and ``{"from", "type", "to"}`` edges, with node ids
following the existing ``source-record:``/``startup:`` prefix convention.

That keeps the integration one-directional: nothing in ``graph/`` changes, and a
``TrendSignal`` node joins the graph through ``DERIVED_FROM`` edges to the exact
records it was computed from.

A trend signal is an operational signal, not a claim
----------------------------------------------------
``docs/evidence-ledger.md`` forbids converting a trend score into a claim about
future performance, so nothing here mints a ``Claim`` node or assigns an
evidence state. :func:`ledger_support_note` produces the provenance a ledger
entry needs; deciding whether a claim is emerging, corroborated, disputed, or
stale remains the evidence ledger's decision.

Two ontology additions are needed before trend signals can also be exported to
RDF/SHACL (listed for Mehmet in the pull request): a ``ts:TrendSignal`` class
and a shape for it. ``ts:derivedFrom`` already exists in
``ontology/trendscout.ttl``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from signals.contract import validate_trend_signal

#: Mirrors the identifier guard in ``graph/cypher.py`` so a label or relation
#: type can never be interpolated into Cypher unchecked.
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

TREND_NODE_LABEL = "TrendSignal"
DERIVED_FROM = "DERIVED_FROM"
ABOUT = "ABOUT"

#: Properties copied onto the graph node. Record id lists stay off the node and
#: become edges instead, so the graph is queryable rather than holding arrays.
NODE_PROPERTIES: tuple[str, ...] = (
    "series_id",
    "metric",
    "signal_family",
    "entity_type",
    "entity_id",
    "company_id",
    "iso_week",
    "week_start",
    "week_end",
    "value",
    "value_state",
    "ewma_baseline",
    "residual",
    "scale",
    "scale_method",
    "z_score",
    "trend_score",
    "label",
    "label_reason",
    "observed_weeks_used",
    "residual_points_used",
    "gap_policy",
    "unit",
    "feature_version",
)


def _node(node_id: str, node_label: str, properties: Mapping[str, Any]) -> dict[str, Any]:
    # Properties are passed as a mapping rather than keyword arguments because a
    # trend signal has its own ``label`` field (rising/flat/falling) that would
    # otherwise collide with the graph node label.
    if not _IDENTIFIER.fullmatch(node_label):
        raise ValueError(f"unsafe graph label: {node_label}")
    return {"id": node_id, "label": node_label, "properties": dict(properties)}


def trend_signal_to_graph(signal: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Convert one validated trend signal into graph-ready nodes and edges."""
    errors = validate_trend_signal(signal)
    if errors:
        raise ValueError(
            f"cannot import invalid trend signal {signal.get('trend_id')}: {errors}"
        )

    trend_id = signal["trend_id"]
    config = signal.get("config") or {}
    properties = {key: signal.get(key) for key in NODE_PROPERTIES}
    properties.update(
        trend_id=trend_id,
        config_fingerprint=config.get("fingerprint"),
        alpha=config.get("alpha"),
        window=config.get("window"),
        threshold=config.get("threshold"),
        min_history=config.get("min_history"),
        interpretation=(
            "describes observed weekly activity relative to its own recent baseline; "
            "not a prediction of future performance"
        ),
    )

    nodes = [_node(trend_id, TREND_NODE_LABEL, properties)]
    edges: list[dict[str, str]] = []

    company_id = signal.get("company_id")
    if company_id:
        company_node = f"startup:{company_id}"
        nodes.append(_node(company_node, "Startup", {"company_id": company_id}))
        edges.append({"from": trend_id, "type": ABOUT, "to": company_node})

    # Direct evidence for this week, then the baseline it was compared against.
    # Both are retained so the ledger can audit the comparison, not just the
    # current value.
    direct = list(signal.get("record_ids") or [])
    window = [
        record_id
        for record_id in (signal.get("window_record_ids") or [])
        if record_id not in set(direct)
    ]
    for record_id in direct + window:
        edges.append(
            {
                "from": trend_id,
                "type": DERIVED_FROM,
                "to": f"source-record:{record_id}",
            }
        )
    return {"nodes": nodes, "edges": edges}


def trend_signals_to_graph(
    signals: Iterable[Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Build a deterministic payload for many signals, merging shared nodes."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()
    for signal in signals:
        payload = trend_signal_to_graph(signal)
        for node in payload["nodes"]:
            existing = nodes.get(node["id"])
            if existing is not None and existing != node:
                # Startup stubs repeat across signals and must agree, exactly as
                # records_to_graph requires for shared nodes.
                raise ValueError(f"conflicting graph node properties for {node['id']}")
            nodes[node["id"]] = node
        for edge in payload["edges"]:
            edges.add((edge["from"], edge["type"], edge["to"]))
    return {
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": [
            {"from": source, "type": relation, "to": target}
            for source, relation, target in sorted(edges)
        ],
    }


def trend_import_statements(
    signals: Iterable[Mapping[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    """Parameterized Cypher for trend signals, without opening a connection.

    Deliberately a copy of the statement shape in ``graph/cypher.py`` rather
    than a change to it. ``MATCH`` on the record side means a signal never
    creates a source record that was not loaded: if the records are missing, the
    edge is simply not written, which is the honest outcome.
    """
    payload = trend_signals_to_graph(signals)
    statements: list[tuple[str, dict[str, Any]]] = []
    for node in payload["nodes"]:
        label = node["label"]
        if not _IDENTIFIER.fullmatch(label):
            raise ValueError(f"unsafe graph label: {label}")
        statements.append(
            (
                f"MERGE (node:{label} {{id: $id}}) SET node += $properties",
                {"id": node["id"], "properties": {**node["properties"], "id": node["id"]}},
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
                {"source_id": edge["from"], "target_id": edge["to"]},
            )
        )
    return statements


def ledger_support_note(signal: Mapping[str, Any]) -> dict[str, Any]:
    """Provenance for an evidence-ledger entry supported by a trend signal.

    Returns the fields ``docs/evidence-ledger.md`` lists as the minimum entry
    content that a trend signal can actually supply. It assigns **no** evidence
    state and no confidence: a trend signal is one operational signal, and
    whether that makes a claim emerging or corroborated depends on the other
    evidence the ledger holds.
    """
    errors = validate_trend_signal(signal)
    if errors:
        raise ValueError(f"cannot describe invalid trend signal {signal.get('trend_id')}: {errors}")
    config = signal.get("config") or {}
    return {
        "signal_id": signal["trend_id"],
        "signal_kind": "weekly_trend",
        "subject_company_id": signal.get("company_id"),
        "metric": signal["metric"],
        "signal_family": signal["signal_family"],
        "entity_type": signal["entity_type"],
        "entity_id": signal["entity_id"],
        "valid_from": signal["week_start"],
        "valid_to": signal["week_end"],
        "iso_week": signal["iso_week"],
        "observation": {
            "value": signal.get("value"),
            "value_state": signal["value_state"],
            "baseline": signal.get("ewma_baseline"),
            "trend_score": signal.get("trend_score"),
            "label": signal["label"],
            "reason": signal["label_reason"],
        },
        "supporting_record_ids": list(signal.get("record_ids") or []),
        "baseline_record_ids": list(signal.get("window_record_ids") or []),
        "origin_cluster_ids": list(signal.get("origin_cluster_ids") or []),
        "extraction_method": signal["feature_version"],
        "method_parameters": {
            "alpha": config.get("alpha"),
            "window": config.get("window"),
            "threshold": config.get("threshold"),
            "min_history": config.get("min_history"),
            "scale_method": config.get("scale_method"),
            "fingerprint": config.get("fingerprint"),
        },
        "evidence_state": None,
        "evidence_state_note": (
            "state is assigned by the evidence ledger, not by the trend module; one trend "
            "signal is a single operational signal and never a claim about future performance"
        ),
    }


__all__ = [
    "ABOUT",
    "DERIVED_FROM",
    "NODE_PROPERTIES",
    "TREND_NODE_LABEL",
    "ledger_support_note",
    "trend_import_statements",
    "trend_signal_to_graph",
    "trend_signals_to_graph",
]
