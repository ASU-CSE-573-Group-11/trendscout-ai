"""Shared record normalization and validation."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

from .records import canonicalize_url, sha256_text

API_COLLECTOR_VERSION = "api-collectors/0.2.0"


class CollectorError(ValueError):
    """Collection or validation failed."""


def utc_timestamp(value: str | None = None) -> str:
    if value is None:
        dt = datetime.now(timezone.utc)
    else:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise CollectorError("Expected an ISO-8601 timestamp with a timezone") from exc
        if dt.tzinfo is None:
            raise CollectorError("Timestamp must include a timezone")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CollectorError(f"Missing or invalid {field}")
    return value.strip()


def public_url(value) -> str:
    value = required_text(value, "source_url")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise CollectorError("Expected a public HTTP(S) source URL")
    return value


def source_id(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise CollectorError("Missing or invalid source item ID")
    return required_text(str(value), "source item ID")


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CollectorError("Description must be text")
    parser = _TextParser()
    # Greenhouse descriptions may contain escaped HTML.
    parser.feed(html.unescape(value))
    return " ".join("".join(parser.parts).split())


# Explicit mentions only; no inferred requirements.
SKILLS = {
    "python": r"\bpython\b",
    "c++": r"(?<!\w)c\+\+(?!\w)",
    "sql": r"\bsql\b",
    "pytorch": r"\bpytorch\b",
    "cuda": r"\bcuda\b",
    "kubernetes": r"\bkubernetes\b",
    "docker": r"\bdocker\b",
    "tensorflow": r"\btensorflow\b",
    "javascript": r"\bjavascript\b",
    "typescript": r"\btypescript\b",
    "rust": r"\brust\b",
}


def job_fields(title: str, description: str) -> dict:
    text = f"{title} {description}"
    return {
        "title": title,
        "role_normalized": " ".join(title.casefold().split()),
        "skills": sorted(name for name, pattern in SKILLS.items()
                         if re.search(pattern, text, re.IGNORECASE)),
        "skill_extraction_method": "explicit_mentions_v1",
    }


def make_record(snapshot: dict, item_id: str, url: str, text: str,
                metadata: dict, *, source_type: str, event_type: str,
                published_at: str | None = None) -> dict:
    source = snapshot["source"]
    company_id = required_text(snapshot.get("company_id"), "company_id")
    company_name = required_text(snapshot.get("company_name"), "company_name")
    identity = f"{source}:{snapshot['target']}:{item_id}"
    url = canonicalize_url(public_url(url))
    origin = snapshot.get("origin_cluster_id")
    # Migrate the old company-level default to a document origin.
    if snapshot.get("snapshot_version") == 1 and origin == f"company:{company_id}":
        origin = None
    origin = origin or sha256_text(url)[:16]
    metadata = {
        **metadata, "collector": source, "source_record_id": identity,
        "source_control_group": f"company:{company_id}",
    }
    record = {
        "source_type": source_type, "source_url": url,
        "publisher": company_name, "startup_name": company_name,
        "company_id": company_id, "origin_cluster_id": origin,
        "title": metadata.get("title") or metadata.get("repository"),
        "collector_version": API_COLLECTOR_VERSION,
        "event_type": event_type, "event_at": None,
        "published_at": published_at, "text": text,
        "access_note": "Public read-only API; no applicant or private-profile data.",
        "metadata": metadata,
    }
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record.update(record_id=f"{identity}:{digest}", content_hash=digest,
                  observed_at=utc_timestamp(snapshot["observed_at"]))
    return record


def validate_records(records: list[dict], schema_path: Path | None = None) -> list[dict]:
    schema_path = schema_path or Path(__file__).resolve().parents[1] / "schemas/record.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    unique = {}
    for record in records:
        validator.validate(record)
        required_text(record.get("company_id"), "company_id")
        required_text(record.get("origin_cluster_id"), "origin_cluster_id")
        identity = record["metadata"]["source_record_id"]
        if identity in unique and unique[identity]["content_hash"] != record["content_hash"]:
            raise CollectorError("Conflicting duplicate source IDs; retry the snapshot")
        unique.setdefault(identity, record)
    return sorted(unique.values(), key=lambda record: record["record_id"])
