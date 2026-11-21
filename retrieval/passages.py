"""Passages: the retrieval unit shared by the lexical and dense indexes.

One passage per source record by default, matching what ``retrieval/bm25.py``
already indexes (``title`` plus ``text``). Keeping the unit identical is what
makes a BM25-versus-dense comparison on the frozen snapshot meaningful; if one
index scored chunks and the other scored whole records, Precision@5 would not be
comparable between them.

Chunking is available for long passages but is off by default, and turning it on
changes the retrieval unit for every retriever at once, never for one of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Passage:
    """One retrievable passage, carrying the provenance an answer must cite."""

    passage_id: str
    record_id: str
    company_id: str | None
    origin_cluster_id: str
    source_type: str
    title: str | None
    text: str
    publisher: str | None = None
    source_url: str | None = None
    observed_at: str | None = None
    published_at: str | None = None
    event_at: str | None = None
    chunk_index: int = 0
    chunk_count: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        """The text both indexes score, so neither sees more than the other."""
        return f"{self.title or ''} {self.text}".strip()

    @property
    def best_time(self) -> str | None:
        """The most specific time available, preferring event over publication."""
        return self.event_at or self.published_at or self.observed_at

    @property
    def time_basis(self) -> str | None:
        if self.event_at:
            return "event_at"
        if self.published_at:
            return "published_at"
        if self.observed_at:
            return "observed_at"
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "passage_id": self.passage_id,
            "record_id": self.record_id,
            "company_id": self.company_id,
            "origin_cluster_id": self.origin_cluster_id,
            "source_type": self.source_type,
            "title": self.title,
            "text": self.text,
            "publisher": self.publisher,
            "source_url": self.source_url,
            "observed_at": self.observed_at,
            "published_at": self.published_at,
            "event_at": self.event_at,
            "chunk_index": self.chunk_index,
            "chunk_count": self.chunk_count,
        }


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split on sentence-ish boundaries without losing any characters."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if cut < max_chars // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_chars
        else:
            cut += 1
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def passage_from_record(record: Mapping[str, Any], *, chunk_index: int = 0, chunk_count: int = 1, text: str | None = None) -> Passage:
    passage_id = record["record_id"] if chunk_count == 1 else f"{record['record_id']}#{chunk_index}"
    return Passage(
        passage_id=passage_id,
        record_id=record["record_id"],
        company_id=record.get("company_id"),
        origin_cluster_id=record["origin_cluster_id"],
        source_type=str(record.get("source_type")),
        title=record.get("title"),
        text=text if text is not None else (record.get("text") or ""),
        publisher=record.get("publisher"),
        source_url=record.get("source_url"),
        observed_at=record.get("observed_at"),
        published_at=record.get("published_at"),
        event_at=record.get("event_at"),
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        metadata=record.get("metadata") or {},
    )


def passages_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    max_chars: int | None = None,
    source_types: Sequence[str] | None = None,
    include_empty: bool = False,
) -> list[Passage]:
    """Build passages from records.

    ``max_chars`` splits long passages; leaving it ``None`` keeps one passage per
    record, which is the default so the retrievers stay comparable.

    Passages are deduplicated by ``passage_id``. A snapshot replayed into the
    same file repeats a record verbatim -- same ``record_id``, same
    ``content_hash`` -- and indexing it twice would let one piece of evidence
    occupy two result slots.
    """
    wanted = set(source_types) if source_types else None
    passages: dict[str, Passage] = {}
    for record in records:
        if wanted is not None and record.get("source_type") not in wanted:
            continue
        text = record.get("text") or ""
        if not text.strip() and not include_empty:
            # A record with no retained passage cannot support a cited answer.
            continue
        if max_chars is None:
            candidates = [passage_from_record(record)]
        else:
            chunks = _split_text(text, max_chars) or [text]
            candidates = [
                passage_from_record(record, chunk_index=index, chunk_count=len(chunks), text=chunk)
                for index, chunk in enumerate(chunks)
            ]
        for passage in candidates:
            passages.setdefault(passage.passage_id, passage)
    return list(passages.values())


__all__ = ["Passage", "passage_from_record", "passages_from_records"]
