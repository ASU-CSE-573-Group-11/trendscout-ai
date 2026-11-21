"""Hybrid retrieval: reciprocal rank fusion over BM25 and the dense index.

Sueda's ``retrieval/bm25.py`` is used exactly as it is -- constructed, queried,
and otherwise untouched. Fusion happens here, on the returned hit lists.

Why reciprocal rank fusion
--------------------------
BM25 scores and cosine similarities are on different, unnormalized scales, so
adding or averaging them would silently weight one retriever by whatever range
its scores happen to occupy. RRF uses only ranks:

    score(d) = sum over retrievers of weight / (k + rank(d))

with ``rank`` 1-based and ``k`` damping the top positions (60 is the usual
default). It needs no score calibration and no training data, which suits a
frozen snapshot with no relevance labels yet.

Ablations are first-class: a retriever can be disabled, the fusion constant and
per-retriever weights are configurable, and ``distinct_origins`` can be turned
off, so Sueda and Mehmet can run BM25-only, dense-only, and hybrid conditions
from one entry point without editing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from retrieval.bm25 import BM25Index
from retrieval.dense import DenseIndex, Encoder
from retrieval.passages import Passage, passages_from_records

RETRIEVERS: tuple[str, ...] = ("bm25", "dense")
DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class RetrievalConfig:
    """Retrieval mode, fusion parameters, and the ablation switches."""

    mode: str = "hybrid"
    rrf_k: int = DEFAULT_RRF_K
    weights: Mapping[str, float] = field(default_factory=lambda: {"bm25": 1.0, "dense": 1.0})
    distinct_origins: bool = True
    candidate_multiplier: int = 4

    def __post_init__(self) -> None:
        if self.mode not in {"hybrid", "bm25", "dense"}:
            raise ValueError(f"unsupported retrieval mode: {self.mode}")
        if self.rrf_k < 1:
            raise ValueError("rrf_k must be at least 1")
        if self.candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be at least 1")

    @property
    def active_retrievers(self) -> tuple[str, ...]:
        if self.mode == "hybrid":
            return RETRIEVERS
        return (self.mode,)


@dataclass
class HybridRetriever:
    """BM25 plus dense retrieval over one passage set."""

    passages: list[Passage]
    bm25: BM25Index
    dense: DenseIndex
    config: RetrievalConfig = field(default_factory=RetrievalConfig)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        encoder: Encoder | None = None,
        config: RetrievalConfig | None = None,
        max_chars: int | None = None,
        source_types: Sequence[str] | None = None,
        dense_index: DenseIndex | None = None,
    ) -> "HybridRetriever":
        passages = passages_from_records(records, max_chars=max_chars, source_types=source_types)
        return cls.from_passages(passages, encoder=encoder, config=config, dense_index=dense_index)

    @classmethod
    def from_passages(
        cls,
        passages: Sequence[Passage],
        *,
        encoder: Encoder | None = None,
        config: RetrievalConfig | None = None,
        dense_index: DenseIndex | None = None,
    ) -> "HybridRetriever":
        passages = list(passages)
        # BM25 is given the same passage set, shaped as the records it expects.
        # Its own code is not modified; only its input is prepared here.
        bm25 = BM25Index.from_records([_bm25_document(passage) for passage in passages])
        dense = dense_index or DenseIndex.from_passages(passages, encoder=encoder)
        if dense_index is not None and {passage.passage_id for passage in dense_index.passages} != {
            passage.passage_id for passage in passages
        }:
            raise ValueError(
                "the persisted dense index covers a different passage set than this snapshot; "
                "rebuild it so the two retrievers rank the same documents"
            )
        return cls(passages=passages, bm25=bm25, dense=dense, config=config or RetrievalConfig())

    # -- retrieval -------------------------------------------------------

    def _by_id(self) -> dict[str, Passage]:
        return {passage.passage_id: passage for passage in self.passages}

    def _bm25_hits(self, query: str, limit: int | None) -> list[dict[str, Any]]:
        hits = self.bm25.search(query, k=limit)
        lookup = self._by_id()
        prepared = []
        for hit in hits:
            passage = lookup.get(hit["record_id"])
            if passage is None:
                continue
            prepared.append(
                {
                    "score": hit["score"],
                    "passage_id": passage.passage_id,
                    "record_id": passage.record_id,
                    "origin_cluster_id": passage.origin_cluster_id,
                    "passage": passage,
                    "retriever": "bm25",
                }
            )
        return prepared

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        config: RetrievalConfig | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve and fuse, returning at most ``k`` hits."""
        config = config or self.config
        if k < 1:
            raise ValueError("k must be at least 1")
        candidate_k = max(k * config.candidate_multiplier, k)

        per_retriever: dict[str, list[dict[str, Any]]] = {}
        if "bm25" in config.active_retrievers:
            per_retriever["bm25"] = self._bm25_hits(query, candidate_k)
        if "dense" in config.active_retrievers:
            per_retriever["dense"] = self.dense.search(query, k=candidate_k)

        fused = fuse(per_retriever, rrf_k=config.rrf_k, weights=config.weights)
        if config.distinct_origins:
            fused = limit_to_distinct_origins(fused, k)
        return fused[:k]

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.config.mode,
            "rrf_k": self.config.rrf_k,
            "weights": dict(self.config.weights),
            "distinct_origins": self.config.distinct_origins,
            "passages": len(self.passages),
            "records": len({passage.record_id for passage in self.passages}),
            "dense": self.dense.describe(),
            "fusion": "reciprocal_rank_fusion",
        }


def _bm25_document(passage: Passage) -> dict[str, Any]:
    """Shape a passage as the record dict BM25Index.from_records consumes."""
    return {
        "record_id": passage.passage_id,
        "origin_cluster_id": passage.origin_cluster_id,
        "title": passage.title,
        "text": passage.text,
    }


def fuse(
    per_retriever: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    rrf_k: int = DEFAULT_RRF_K,
    weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Reciprocal rank fusion over several ranked hit lists.

    The per-retriever rank and raw score of every fused hit are retained, so a
    result can be explained and an ablation can be checked afterwards.
    """
    weights = weights or {}
    merged: dict[str, dict[str, Any]] = {}
    for retriever, hits in per_retriever.items():
        weight = float(weights.get(retriever, 1.0))
        for rank, hit in enumerate(hits, start=1):
            passage_id = hit["passage_id"]
            entry = merged.get(passage_id)
            if entry is None:
                entry = {
                    "passage_id": passage_id,
                    "record_id": hit["record_id"],
                    "origin_cluster_id": hit["origin_cluster_id"],
                    "passage": hit["passage"],
                    "score": 0.0,
                    "retrievers": {},
                }
                merged[passage_id] = entry
            entry["score"] += weight / (rrf_k + rank)
            entry["retrievers"][retriever] = {"rank": rank, "score": hit["score"]}

    fused = list(merged.values())
    # Deterministic ordering: fused score, then number of retrievers that found
    # it, then passage id, so repeated runs on a frozen snapshot agree exactly.
    fused.sort(key=lambda hit: (-hit["score"], -len(hit["retrievers"]), hit["passage_id"]))
    for rank, hit in enumerate(fused, start=1):
        hit["rank"] = rank
    return fused


def limit_to_distinct_origins(
    hits: Sequence[Mapping[str, Any]], k: int
) -> list[dict[str, Any]]:
    """Keep at most one hit per origin cluster, preserving fused order.

    Mirrors ``retrieval/handoff.search_snapshot``: syndicated copies of one
    origin must not crowd a result set, and they are not independent
    corroboration either.
    """
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        origin = hit["origin_cluster_id"]
        if origin in seen:
            continue
        seen.add(origin)
        selected.append(dict(hit))
        if len(selected) == k:
            break
    return selected


__all__ = [
    "DEFAULT_RRF_K",
    "RETRIEVERS",
    "HybridRetriever",
    "RetrievalConfig",
    "fuse",
    "limit_to_distinct_origins",
]
