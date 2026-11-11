"""Load Mehmet's Cypher queries as named, parameterized templates.

The queries in ``graph/*.cypher`` are the project's competency queries. Rather
than restate them in Python, this module reads those files, splits them into
statements, names each one from its leading comment, and extracts its ``$``
parameters. The router then selects a template by purpose, and the selected
Cypher text travels with the answer as the graph query that was run.

Nothing in ``graph/`` is modified. If a query is reworded the slug changes, so
selection is by a distinctive phrase rather than by file position, and a missing
template is reported rather than raising: an answer that cannot show its graph
query should say so, not crash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

GRAPH_DIR = Path(__file__).resolve().parents[1] / "graph"

CYPHER_FILES: tuple[str, ...] = (
    "competency_queries.cypher",
    "evidence_queries.cypher",
    "temporal_queries.cypher",
)

_PARAMETER = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_WORD = re.compile(r"[a-z0-9]+")

#: Purpose -> a phrase that must appear in the template's description. Keyed on
#: wording rather than order so a reordered file does not silently change which
#: query runs.
TEMPLATE_PURPOSES: dict[str, str] = {
    "company_records": "source records for one startup",
    "independent_origins": "independent documentary origins",
    "records_in_window": "evidence observed inside a requested time window",
    "publisher_path": "provenance path from a startup to its source publisher",
    "claims_for_record": "claims supported by one source record",
    "claims_in_state": "claims for one startup in a selected evidence state",
    "claim_origins": "independent origins supporting each claim",
    "claim_window_path": "evidence path for a temporal claim review",
    "temporal_multihop": "temporal multi-hop evidence path",
    "corroboration_threshold": "require independent origins before treating a claim as corroborated",
    "latest_state_path": "return the latest evidence state while retaining the supporting path",
}


@dataclass(frozen=True)
class CypherTemplate:
    """One named query from ``graph/*.cypher``."""

    name: str
    description: str
    query: str
    parameters: tuple[str, ...]
    source_file: str

    def bind(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Select the parameters this template needs from ``values``.

        Missing parameters are reported by name instead of being defaulted,
        because a silently defaulted time window would produce a confidently
        wrong answer.
        """
        missing = [name for name in self.parameters if name not in values]
        if missing:
            raise KeyError(f"template {self.name!r} needs parameters {missing}")
        return {name: values[name] for name in self.parameters}

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "query": self.query,
            "parameters": list(self.parameters),
            "source_file": self.source_file,
        }


def _slug(description: str) -> str:
    return "_".join(_WORD.findall(description.lower()))[:60] or "query"


def _split_statements(text: str) -> list[tuple[str, str]]:
    """Return ``(description, query)`` pairs from one .cypher file."""
    statements: list[tuple[str, str]] = []
    comments: list[str] = []
    body: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if not body:
                comments = []
            continue
        if line.lstrip().startswith("//"):
            if body:
                statements.append((" ".join(comments).strip(), "\n".join(body).strip()))
                body, comments = [], []
            comments.append(line.lstrip()[2:].strip())
            continue
        body.append(line)
        if line.rstrip().endswith(";"):
            statements.append((" ".join(comments).strip(), "\n".join(body).strip()))
            body, comments = [], []
    if body:
        statements.append((" ".join(comments).strip(), "\n".join(body).strip()))
    return [(description, query) for description, query in statements if query]


def load_cypher_templates(graph_dir: Path | None = None) -> list[CypherTemplate]:
    """Read every query in ``graph/*.cypher``."""
    graph_dir = graph_dir or GRAPH_DIR
    templates: list[CypherTemplate] = []
    for file_name in CYPHER_FILES:
        path = graph_dir / file_name
        if not path.exists():
            continue
        for description, query in _split_statements(path.read_text(encoding="utf-8")):
            templates.append(
                CypherTemplate(
                    name=_slug(description or query),
                    description=description or "(no description comment)",
                    query=query,
                    parameters=tuple(sorted(set(_PARAMETER.findall(query)))),
                    source_file=file_name,
                )
            )
    return templates


class CypherLibrary:
    """Named access to the graph queries, by purpose."""

    def __init__(self, templates: Iterable[CypherTemplate] | None = None) -> None:
        self.templates = list(templates) if templates is not None else load_cypher_templates()
        self._by_name = {template.name: template for template in self.templates}
        self._by_purpose: dict[str, CypherTemplate] = {}
        for purpose, phrase in TEMPLATE_PURPOSES.items():
            needle = phrase.lower()
            for template in self.templates:
                if needle in template.description.lower():
                    self._by_purpose[purpose] = template
                    break

    def __len__(self) -> int:
        return len(self.templates)

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def purposes(self) -> list[str]:
        return sorted(self._by_purpose)

    def missing_purposes(self) -> list[str]:
        return sorted(set(TEMPLATE_PURPOSES) - set(self._by_purpose))

    def by_name(self, name: str) -> CypherTemplate | None:
        return self._by_name.get(name)

    def for_purpose(self, purpose: str) -> CypherTemplate | None:
        return self._by_purpose.get(purpose)

    def describe(self) -> dict[str, Any]:
        return {
            "template_count": len(self.templates),
            "files": list(CYPHER_FILES),
            "purposes_resolved": self.purposes(),
            "purposes_missing": self.missing_purposes(),
        }


__all__ = [
    "CYPHER_FILES",
    "GRAPH_DIR",
    "TEMPLATE_PURPOSES",
    "CypherLibrary",
    "CypherTemplate",
    "load_cypher_templates",
]
