from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from graph.import_contract import merge_graph_payloads, records_to_graph

TS = Namespace("https://example.org/trendscout/")
PROV = Namespace("http://www.w3.org/ns/prov#")

_RELATION_PREDICATES = {
    "ABOUT": TS.about,
    "PUBLISHED_BY": TS.publishedBy,
    "MEMBER_OF_ORIGIN": TS.memberOfOrigin,
    "SUPPORTS": TS.supports,
    "DOCUMENTS": TS.documents,
    "MENTIONS": TS.mentions,
    "BACKS": TS.backs,
    "CLAIM_SUBJECT": TS.claimSubject,
    "FUNDING_OF": TS.fundingOf,
    "HAS_JOB_POSTING": TS.hasJobPosting,
    "HAS_REPOSITORY": TS.hasRepository,
    "REQUIRES_SKILL": TS.requiresSkill,
    "USES_TECHNOLOGY": TS.usesTechnology,
}

_NODE_CLASSES = {
    "SourceRecord": TS.SourceRecord,
    "Startup": TS.Startup,
    "Publisher": TS.Publisher,
    "OriginCluster": TS.OriginCluster,
    "Claim": TS.Claim,
    "Investor": TS.Investor,
    "FundingRound": TS.FundingRound,
    "JobPosting": TS.JobPosting,
    "Repository": TS.Repository,
    "Skill": TS.Skill,
    "Technology": TS.Technology,
    "Product": TS.Product,
    "Voice": TS.Voice,
}

_PROPERTY_PREDICATES = {
    "record_id": TS.recordId,
    "company_id": TS.companyId,
    "source_type": TS.sourceType,
    "source_url": TS.sourceUrl,
    "title": TS.title,
    "passage": TS.passage,
    "event_at": TS.eventAt,
    "published_at": TS.publishedAt,
    "observed_at": TS.observedAt,
    "content_hash": TS.contentHash,
    "origin_cluster_id": TS.originClusterId,
    "collector_version": TS.collectorVersion,
    "name": TS.name,
    "claim_text": TS.claimText,
    "state": TS.state,
    "confidence": TS.confidence,
    "extraction_method": TS.extractionMethod,
    "state_changed_at": TS.stateChangedAt,
    "reason": TS.reason,
    "claim_id": TS.claimId,
    "round_id": TS.roundId,
    "amount": TS.amount,
    "currency": TS.currency,
    "job_posting_id": TS.jobPostingId,
    "repository_id": TS.repositoryId,
    "source_record_id": TS.sourceRecordId,
    "listed_at": TS.listedAt,
    "announced_at": TS.announcedAt,
    "source_updated_at": TS.sourceUpdatedAt,
    "source_pushed_at": TS.sourcePushedAt,
    "default_branch": TS.defaultBranch,
    "license_spdx": TS.licenseSpdx,
    "event_date_basis": TS.eventDateBasis,
    "skill_extraction_method": TS.skillExtractionMethod,
}

_DATETIME_PROPERTIES = {
    "event_at",
    "published_at",
    "observed_at",
    "state_changed_at",
    "listed_at",
    "announced_at",
    "source_updated_at",
    "source_pushed_at",
}


def _uri(node_id: str) -> URIRef:
    return TS[node_id.replace(":", "/")]


def _literal(key: str, value: Any) -> Literal:
    if key in _DATETIME_PROPERTIES:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return Literal(value, datatype=XSD.dateTime)
    if key in {"confidence", "amount"}:
        lexical = f"{value}.0" if key == "amount" and isinstance(value, int) else str(value)
        return Literal(Decimal(lexical), datatype=XSD.decimal)
    if key == "source_url":
        return Literal(value, datatype=XSD.anyURI)
    return Literal(value)


def graph_to_rdf(records: Iterable[dict[str, Any]]) -> Graph:
    """Convert validated source records into an RDF graph with PROV-O links."""
    return graph_payload_to_rdf(records_to_graph(records))


def graph_payload_to_rdf(payload: dict[str, list[dict[str, Any]]]) -> Graph:
    """Convert a validated storage-neutral graph payload to RDF."""
    payload = merge_graph_payloads(payload)
    graph = Graph()
    graph.bind("ts", TS)
    graph.bind("prov", PROV)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)

    for node in payload["nodes"]:
        subject = _uri(node["id"])
        label = node["label"]
        node_class = _NODE_CLASSES.get(label)
        if node_class is None:
            raise ValueError(f"unsupported graph node label for RDF export: {label}")
        graph.add((subject, RDF.type, node_class))
        for key, value in node["properties"].items():
            if value is None:
                continue
            predicate = _PROPERTY_PREDICATES.get(key)
            if predicate is None:
                raise ValueError(f"unsupported graph property for RDF export: {key}")
            graph.add((subject, predicate, _literal(key, value)))

    for edge in payload["edges"]:
        predicate = _RELATION_PREDICATES.get(edge["type"])
        if predicate is None:
            raise ValueError(f"unsupported graph relation for RDF export: {edge['type']}")
        graph.add((_uri(edge["from"]), predicate, _uri(edge["to"])))
    return graph


def serialize_rdf(records: Iterable[dict[str, Any]], *, format: str = "turtle") -> str:
    """Serialize a record collection as RDF, defaulting to Turtle."""
    return graph_to_rdf(records).serialize(format=format)


def serialize_graph_payload(
    payload: dict[str, list[dict[str, Any]]], *, format: str = "turtle"
) -> str:
    """Serialize a complete graph payload, defaulting to Turtle."""
    return graph_payload_to_rdf(payload).serialize(format=format)
