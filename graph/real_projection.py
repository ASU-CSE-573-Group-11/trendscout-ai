from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from graph.evidence import make_evidence_entry
from graph.import_contract import merge_graph_payloads, records_to_graph


TECHNOLOGY_TERMS = {
    "javascript",
    "kubernetes",
    "nlp",
    "python",
    "pytorch",
    "rag",
    "sql",
    "typescript",
}

_FUNDING_PATTERN = re.compile(
    r"\$(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[MB])\b.{0,80}?\b(?P<round>Series\s+[A-Z])\b",
    re.IGNORECASE,
)


def _node(node_id: str, label: str, **properties: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "properties": {key: value for key, value in properties.items() if value is not None},
    }


def _edge(source: str, relation: str, target: str) -> dict[str, str]:
    return {"from": source, "type": relation, "to": target}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise ValueError("cannot create an empty graph identifier")
    return slug


def _funding_fields(record: dict[str, Any]) -> tuple[str, int, str]:
    searchable = f"{record.get('title') or ''}\n{record['text'][:1200]}"
    match = _FUNDING_PATTERN.search(searchable)
    if not match:
        raise ValueError(f"funding record has no explicit amount/round pair: {record['record_id']}")
    multiplier = 1_000_000 if match.group("unit").upper() == "M" else 1_000_000_000
    amount = int(Decimal(match.group("amount")) * multiplier)
    round_name = "Series " + match.group("round").split()[-1].upper()
    return round_name, amount, "USD"


def _claim_text(record: dict[str, Any]) -> str:
    if record["source_type"] == "funding":
        pattern = r"\b(raised|raises|funding|financing)\b"
    elif record["source_type"] == "job":
        pattern = r"\b(role|responsibilities|hiring|engineer\w*|looking for)\b"
    else:
        pattern = None
    match = re.search(pattern, record["text"], re.IGNORECASE) if pattern else None
    start = max(0, match.start() - 100) if match else 0
    return record["text"][start : start + 300]


def build_real_graph(
    records: Iterable[dict[str, Any]],
    entity_rows: Iterable[dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """Project frozen real records into a provenance-bound semantic graph.

    The projection creates observed public-listing and announcement nodes. It
    never equates a listing with a completed hire, infers an unknown funding
    event date, or assigns an investor to a specific round without that link in
    the retained source.
    """
    records = list(records)
    records_by_id = {record["record_id"]: record for record in records}
    if len(records_by_id) != len(records):
        raise ValueError("record ids must be unique")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    for record in records:
        source_id = f"source-record:{record['record_id']}"
        startup_id = f"startup:{record['company_id']}"

        evidence = make_evidence_entry(
            record,
            claim_text=_claim_text(record),
            extraction_method="source_excerpt",
            reason="Single retained source excerpt; no growth, hire, or causality inference.",
        )
        nodes.append(
            _node(
                evidence["claim_id"],
                "Claim",
                claim_id=evidence["claim_id"],
                claim_text=evidence["claim_text"],
                state=evidence["state"],
                confidence=evidence["confidence"],
                extraction_method=evidence["extraction_method"],
                state_changed_at=evidence["state_changed_at"],
                reason=evidence["reason"],
            )
        )
        edges.append(_edge(source_id, "SUPPORTS", evidence["claim_id"]))
        edges.append(_edge(evidence["claim_id"], "CLAIM_SUBJECT", startup_id))

        if record["source_type"] == "funding":
            round_name, amount, currency = _funding_fields(record)
            round_id = f"funding-round:{record['record_id']}"
            nodes.append(
                _node(
                    round_id,
                    "FundingRound",
                    round_id=record["record_id"],
                    name=round_name,
                    amount=amount,
                    currency=currency,
                    observed_at=record["observed_at"],
                    announced_at=record.get("published_at"),
                    event_at=record.get("event_at"),
                    source_record_id=record["record_id"],
                    event_date_basis=record.get("metadata", {}).get("event_date_basis"),
                    extraction_method="explicit_amount_round_pattern_v1",
                )
            )
            edges.append(_edge(source_id, "DOCUMENTS", round_id))
            edges.append(_edge(round_id, "FUNDING_OF", startup_id))

        elif record["source_type"] == "job":
            metadata = record.get("metadata", {})
            posting_key = metadata.get("source_record_id")
            if not posting_key or not metadata.get("title"):
                raise ValueError(f"job record lacks stable source metadata: {record['record_id']}")
            posting_id = f"job-posting:{posting_key}"
            nodes.append(
                _node(
                    posting_id,
                    "JobPosting",
                    job_posting_id=posting_key,
                    title=metadata["title"],
                    observed_at=record["observed_at"],
                    listed_at=record.get("published_at"),
                    source_url=record["source_url"],
                    source_record_id=record["record_id"],
                    skill_extraction_method=metadata.get("skill_extraction_method"),
                    extraction_method="frozen_job_metadata_v1",
                )
            )
            edges.append(_edge(source_id, "DOCUMENTS", posting_id))
            edges.append(_edge(startup_id, "HAS_JOB_POSTING", posting_id))
            for raw_skill in metadata.get("skills", []):
                skill_name = str(raw_skill).casefold()
                skill_id = f"skill:{_slug(skill_name)}"
                nodes.append(_node(skill_id, "Skill", name=skill_name))
                edges.append(_edge(posting_id, "REQUIRES_SKILL", skill_id))
                if skill_name in TECHNOLOGY_TERMS:
                    technology_id = f"technology:{_slug(skill_name)}"
                    nodes.append(_node(technology_id, "Technology", name=skill_name))
                    edges.append(_edge(posting_id, "USES_TECHNOLOGY", technology_id))

        elif record["source_type"] == "github":
            metadata = record.get("metadata", {})
            repository_key = metadata.get("repository")
            if not repository_key:
                raise ValueError(f"github record lacks repository identity: {record['record_id']}")
            repository_id = f"repository:{repository_key.casefold()}"
            nodes.append(
                _node(
                    repository_id,
                    "Repository",
                    repository_id=repository_key,
                    name=repository_key,
                    source_url=record["source_url"],
                    default_branch=metadata.get("default_branch"),
                    license_spdx=metadata.get("license_spdx"),
                    source_updated_at=metadata.get("source_updated_at"),
                    source_pushed_at=metadata.get("source_pushed_at"),
                    extraction_method="frozen_github_metadata_v1",
                )
            )
            edges.append(_edge(source_id, "DOCUMENTS", repository_id))
            edges.append(_edge(startup_id, "HAS_REPOSITORY", repository_id))

    for row in entity_rows:
        if row.get("label") != "Investor":
            continue
        record = records_by_id.get(row.get("document_id", ""))
        if record is None:
            raise ValueError(f"entity row references unknown document: {row.get('item_id')}")
        start, end = int(row["start"]), int(row["end"])
        if record["text"][start:end] != row["entity_text"]:
            raise ValueError(f"entity offsets do not match retained source: {row['item_id']}")
        investor_name = row["entity_text"]
        investor_id = f"investor:{_slug(investor_name)}"
        source_id = f"source-record:{record['record_id']}"
        startup_id = f"startup:{record['company_id']}"
        nodes.append(_node(investor_id, "Investor", name=investor_name))
        edges.append(_edge(source_id, "MENTIONS", investor_id))
        context = record["text"][max(0, start - 240) : min(len(record["text"]), end + 80)]
        if re.search(r"backed by leading investors including", context, re.IGNORECASE):
            edges.append(_edge(investor_id, "BACKS", startup_id))

    semantic = {"nodes": nodes, "edges": edges}
    return merge_graph_payloads(records_to_graph(records), semantic)
