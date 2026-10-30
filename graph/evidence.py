from __future__ import annotations

import hashlib
import json
from typing import Any

from collectors.records import validate_record

EVIDENCE_STATES = {"emerging", "corroborated", "disputed", "stale", "insufficient"}


def _claim_id(record_id: str, claim_text: str) -> str:
    digest = hashlib.sha256(f"{record_id}\n{claim_text}".encode("utf-8")).hexdigest()[:20]
    return f"claim:{digest}"


def make_evidence_entry(
    record: dict[str, Any],
    *,
    claim_text: str,
    state: str = "emerging",
    confidence: float = 0.5,
    extraction_method: str = "manual",
    reason: str = "Single independent documentary record.",
) -> dict[str, Any]:
    """Create an auditable claim projection without inventing source dates."""
    errors = validate_record(record)
    if errors:
        raise ValueError(f"cannot create evidence for invalid record {record.get('record_id')}: {errors}")
    if not claim_text.strip():
        raise ValueError("claim_text must not be empty")
    if state not in EVIDENCE_STATES:
        raise ValueError(f"unsupported evidence state: {state}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")

    return {
        "claim_id": _claim_id(record["record_id"], claim_text),
        "claim_text": claim_text.strip(),
        "subject_company_id": record.get("company_id"),
        "state": state,
        "confidence": confidence,
        "record_id": record["record_id"],
        "source_url": record["source_url"],
        "publisher": record.get("publisher"),
        "content_hash": record["content_hash"],
        "origin_cluster_id": record["origin_cluster_id"],
        "event_at": record.get("event_at"),
        "published_at": record.get("published_at"),
        "observed_at": record["observed_at"],
        "extraction_method": extraction_method,
        "state_changed_at": record["observed_at"],
        "reason": reason,
    }


def evidence_to_graph(entry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Project one evidence entry into claim/source graph nodes and edges."""
    claim_id = entry["claim_id"]
    record_id = entry["record_id"]
    claim_node = {
        "id": claim_id,
        "label": "Claim",
        "properties": {
            key: value
            for key, value in entry.items()
            if key not in {"claim_id", "record_id"}
        },
    }
    return {
        "nodes": [claim_node],
        "edges": [
            {
                "from": f"source-record:{record_id}",
                "type": "SUPPORTS",
                "to": claim_id,
            }
        ],
    }


def evidence_json(entry: dict[str, Any]) -> str:
    """Serialize an evidence entry for a ledger snapshot."""
    return json.dumps(entry, ensure_ascii=True, sort_keys=True)
