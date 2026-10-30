from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jsonschema import Draft202012Validator, FormatChecker

from collectors import COLLECTOR_VERSION

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "record.schema.json"
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "s",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in {"http", "https", ""} else parts.scheme
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def parse_datetime(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema(), format_checker=FormatChecker())


def validate_record(record: Mapping[str, Any]) -> list[str]:
    return [error.message for error in validator().iter_errors(record)]


def validate_records(records: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    for record in records:
        record_id = str(record.get("record_id") or "<missing>")
        for message in validate_record(record):
            failures.append((record_id, message))
    return failures


def make_record(
    *,
    source_type: str,
    source_url: str,
    title: str | None,
    text: str | None,
    publisher: str | None,
    company_id: str | None = None,
    startup_name: str | None = None,
    event_type: str | None = None,
    event_at: str | None = None,
    published_at: str | None = None,
    observed_at: str | None = None,
    access_note: str | None = None,
    metadata: dict[str, Any] | None = None,
    collector_version: str = COLLECTOR_VERSION,
) -> dict[str, Any]:
    canonical = canonicalize_url(source_url)
    passage = strip_html(text) if text else None
    title_text = strip_html(title) if title else None
    hash_input = "\n".join(
        [
            canonical,
            title_text or "",
            passage or "",
            published_at or "",
        ]
    )
    content_hash = sha256_text(hash_input)
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{canonical}|{content_hash}"))
    record = {
        "record_id": record_id,
        "company_id": company_id,
        "source_type": source_type,
        "source_url": canonical,
        "publisher": publisher,
        "startup_name": startup_name,
        "title": title_text,
        "event_type": event_type,
        "event_at": parse_datetime(event_at),
        "published_at": parse_datetime(published_at),
        "observed_at": parse_datetime(observed_at) or utc_now(),
        "text": passage,
        "content_hash": content_hash,
        "origin_cluster_id": sha256_text(canonical)[:16],
        "collector_version": collector_version,
        "access_note": access_note,
        "metadata": metadata or {},
    }
    errors = validate_record(record)
    if errors:
        raise ValueError(f"invalid source record for {canonical}: {errors}")
    return record
