from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COHORT_PATH = ROOT / "data" / "registry" / "cohort.json"
DEFAULT_SOURCES_PATH = ROOT / "data" / "registry" / "named_sources.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cohort(path: Path | None = None) -> dict[str, Any]:
    return load_json(path or DEFAULT_COHORT_PATH)


def load_named_sources(path: Path | None = None) -> dict[str, Any]:
    return load_json(path or DEFAULT_SOURCES_PATH)


def included_companies(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    return [company for company in cohort.get("companies", []) if company.get("status") == "included"]


def alias_index(companies: Iterable[dict[str, Any]]) -> list[tuple[str, str, re.Pattern[str]]]:
    compiled: list[tuple[str, str, re.Pattern[str]]] = []
    for company in companies:
        company_id = company["company_id"]
        names = [company["name"], *company.get("aliases", [])]
        for name in names:
            # Ordinary verbs/adjectives must not become company mentions.
            flags = 0 if name.lower() in {'continue', 'modal', 'replicate'} else re.IGNORECASE
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", flags)
            compiled.append((company_id, company["name"], pattern))
    compiled.sort(key=lambda item: len(item[1]), reverse=True)
    return compiled


def match_companies(text: str, aliases: list[tuple[str, str, re.Pattern[str]]]) -> list[tuple[str, str]]:
    haystack = text or ""
    seen: dict[str, str] = {}
    for company_id, name, pattern in aliases:
        context = {'continue': r'continue\.dev|\b(coding|IDE|code assistant|code editor)\b',
                   'modal': r'modal\.com|\b(serverless|GPU|compute|inference)\b',
                   'replicate': r'replicate\.com|\b(model|models|inference|image generation)\b'}.get(company_id)
        if context and not re.search(context, haystack, re.IGNORECASE):
            continue
        if company_id not in seen and pattern.search(haystack):
            seen[company_id] = name
    return list(seen.items())
