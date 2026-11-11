"""Dense passage index with a persistable, dependency-free default.

Encoders
--------
``SentenceTransformerEncoder`` is the real dense baseline: a small local model
(``all-MiniLM-L6-v2`` by default, ``bge-small-en-v1.5`` also fine) loaded through
``sentence-transformers``. It is optional because the repository's CI installs
only ``requirements.txt``.

``HashingEncoder`` is the default so the system runs, and the tests pass,
with no extra dependency and no model download. **It is a lexical encoder, not a
semantic one**: it hashes word unigrams, word bigrams, and character trigrams
into a fixed-width vector with signed random projection. That makes it robust to
morphology and typos, and it is fully deterministic across processes, but it
cannot match paraphrases that share no surface form.

This distinction matters for the evaluation. A "dense retrieval" number produced
with ``HashingEncoder`` is **not** a measurement of dense retrieval; it is a
second lexical baseline. The encoder name is recorded on the index, in the saved
file, and in every answer bundle, so a reported metric always says which encoder
produced it, and :func:`DenseIndex.describe` states plainly whether the index is
semantic.

Backends
--------
Similarity is cosine over L2-normalized vectors, so the search is a dot product.
NumPy is used when importable and a pure-Python loop otherwise; FAISS is used
when available and the index is large enough to be worth it. All three return
the same ranking, and the chosen backend is reported.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from retrieval.passages import Passage, passages_from_records

INDEX_FORMAT_VERSION = 2

_WORD = re.compile(r"[a-z0-9]+")

try:  # pragma: no cover - exercised by whichever backend is installed
    import numpy as _numpy
except ImportError:  # pragma: no cover
    _numpy = None

try:  # pragma: no cover
    import faiss as _faiss
except ImportError:  # pragma: no cover
    _faiss = None


@runtime_checkable
class Encoder(Protocol):
    """Anything that turns texts into L2-normalized vectors of fixed width."""

    name: str
    dim: int
    semantic: bool

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def _tokens(text: str) -> list[str]:
    words = _WORD.findall(text.lower())
    features = list(words)
    features.extend(f"{left}_{right}" for left, right in zip(words, words[1:]))
    for word in words:
        if len(word) > 4:
            padded = f"^{word}$"
            features.extend(padded[index : index + 3] for index in range(len(padded) - 2))
    return features


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


@dataclass
class HashingEncoder:
    """Deterministic signed-hashing encoder over word and character features.

    Lexical, not semantic. Present so the whole pipeline runs offline and in CI
    with no model download; see the module docstring on how to report it.
    """

    dim: int = 384
    name: str = field(init=False)
    semantic: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.dim < 16:
            raise ValueError("dim must be at least 16")
        self.name = f"hashing-{self.dim}"

    def _feature_slot(self, feature: str) -> tuple[int, float]:
        # hashlib rather than hash(): the built-in is salted per process, which
        # would make a persisted index unusable on the next run.
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=9).digest()
        index = int.from_bytes(digest[:8], "big") % self.dim
        sign = 1.0 if digest[8] & 1 else -1.0
        return index, sign

    def encode_one(self, text: str) -> list[float]:
        counts: dict[str, int] = {}
        for feature in _tokens(text):
            counts[feature] = counts.get(feature, 0) + 1
        vector = [0.0] * self.dim
        for feature, count in counts.items():
            index, sign = self._feature_slot(feature)
            vector[index] += sign * (1.0 + math.log(count))
        return _l2_normalize(vector)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.encode_one(text) for text in texts]


@dataclass
class SentenceTransformerEncoder:
    """A small local sentence-transformers model. Optional dependency."""

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 32
    name: str = field(init=False)
    dim: int = field(init=False, default=0)
    semantic: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional path
            raise RuntimeError(
                "sentence-transformers is not installed. Install the interface extras "
                "(requirements-interface.txt) or use the default HashingEncoder."
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        # Renamed in sentence-transformers 5.x; both spellings are supported so
        # the encoder works across the versions a teammate might have pinned.
        dimension = getattr(self._model, "get_embedding_dimension", None) or getattr(
            self._model, "get_sentence_embedding_dimension"
        )
        self.dim = int(dimension())
        self.name = f"st:{self.model_name}"

    def encode(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover - optional path
        vectors = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]


def build_encoder(spec: str | None = None, *, dim: int = 384) -> Encoder:
    """Resolve an encoder from a config string.

    ``"hashing"`` or ``None`` gives the default; ``"hashing:512"`` sets the
    width; anything else is treated as a sentence-transformers model name,
    optionally prefixed ``st:``.
    """
    if not spec or spec == "hashing":
        return HashingEncoder(dim=dim)
    if spec.startswith("hashing:"):
        return HashingEncoder(dim=int(spec.split(":", 1)[1]))
    model_name = spec[3:] if spec.startswith("st:") else spec
    return SentenceTransformerEncoder(model_name=model_name)


@dataclass
class DenseIndex:
    """Cosine-similarity index over passage vectors."""

    encoder: Encoder
    passages: list[Passage] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    backend: str = "python"
    faiss_min_passages: int = 512

    def __post_init__(self) -> None:
        self._matrix = None
        self._faiss_index = None

    # -- construction ----------------------------------------------------

    @classmethod
    def from_passages(
        cls,
        passages: Iterable[Passage],
        *,
        encoder: Encoder | None = None,
        use_faiss: bool = True,
    ) -> "DenseIndex":
        encoder = encoder or HashingEncoder()
        items = list(passages)
        vectors = encoder.encode([passage.search_text for passage in items]) if items else []
        index = cls(encoder=encoder, passages=items, vectors=vectors)
        index._prepare(use_faiss=use_faiss)
        return index

    @classmethod
    def from_records(
        cls,
        records: Iterable[Any],
        *,
        encoder: Encoder | None = None,
        max_chars: int | None = None,
        source_types: Sequence[str] | None = None,
        use_faiss: bool = True,
    ) -> "DenseIndex":
        return cls.from_passages(
            passages_from_records(records, max_chars=max_chars, source_types=source_types),
            encoder=encoder,
            use_faiss=use_faiss,
        )

    def _prepare(self, *, use_faiss: bool = True) -> None:
        self._matrix = None
        self._faiss_index = None
        self.backend = "python"
        if not self.vectors:
            return
        if _numpy is not None:
            self._matrix = _numpy.asarray(self.vectors, dtype="float32")
            self.backend = "numpy"
        if (
            use_faiss
            and _faiss is not None
            and self._matrix is not None
            and len(self.vectors) >= self.faiss_min_passages
        ):  # pragma: no cover - optional path
            self._faiss_index = _faiss.IndexFlatIP(self.encoder.dim)
            self._faiss_index.add(self._matrix)
            self.backend = "faiss"

    # -- search ----------------------------------------------------------

    def search(self, query: str, k: int | None = 5) -> list[dict[str, Any]]:
        """Rank passages by cosine similarity, highest first."""
        if not self.passages:
            return []
        if k is not None and k < 1:
            raise ValueError("k must be at least 1")
        query_vector = self.encoder.encode([query])[0]
        limit = len(self.passages) if k is None else min(k, len(self.passages))

        if self._faiss_index is not None:  # pragma: no cover - optional path
            scores, indices = self._faiss_index.search(
                _numpy.asarray([query_vector], dtype="float32"), limit
            )
            ranked = [(float(score), int(index)) for score, index in zip(scores[0], indices[0]) if index >= 0]
        elif self._matrix is not None:
            similarities = self._matrix @ _numpy.asarray(query_vector, dtype="float32")
            order = _numpy.argsort(-similarities, kind="stable")[:limit]
            ranked = [(float(similarities[index]), int(index)) for index in order]
        else:
            similarities = [
                sum(left * right for left, right in zip(vector, query_vector))
                for vector in self.vectors
            ]
            order = sorted(range(len(similarities)), key=lambda index: (-similarities[index], index))[:limit]
            ranked = [(similarities[index], index) for index in order]

        hits: list[dict[str, Any]] = []
        for score, index in ranked:
            if score <= 0.0:
                continue
            passage = self.passages[index]
            hits.append(
                {
                    "score": float(score),
                    "passage_id": passage.passage_id,
                    "record_id": passage.record_id,
                    "origin_cluster_id": passage.origin_cluster_id,
                    "passage": passage,
                    "retriever": "dense",
                    "encoder": self.encoder.name,
                }
            )
        return hits

    # -- persistence -----------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """What the index is, including whether it is a semantic model."""
        return {
            "encoder": self.encoder.name,
            "dim": self.encoder.dim,
            "semantic": bool(getattr(self.encoder, "semantic", False)),
            "backend": self.backend,
            "passages": len(self.passages),
            "records": len({passage.record_id for passage in self.passages}),
            "format_version": INDEX_FORMAT_VERSION,
            "caveat": (
                None
                if getattr(self.encoder, "semantic", False)
                else "lexical hashing encoder: report results as a second lexical baseline, "
                "not as dense retrieval"
            ),
        }

    def save(self, path: Path, *, precision: int = 6) -> Path:
        """Persist the index beside the frozen snapshot it was built from."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": INDEX_FORMAT_VERSION,
            "describe": self.describe(),
            "passages": [passage.as_dict() for passage in self.passages],
            "vectors": [[round(value, precision) for value in vector] for vector in self.vectors],
        }
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path, *, encoder: Encoder | None = None, use_faiss: bool = True) -> "DenseIndex":
        """Load a persisted index, refusing a mismatched encoder.

        A query encoded by a different encoder than the passages is silently
        meaningless, so the mismatch is an error rather than a warning.
        """
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("format_version") != INDEX_FORMAT_VERSION:
            raise ValueError(
                f"{path} was written by index format {payload.get('format_version')}, "
                f"this build reads {INDEX_FORMAT_VERSION}"
            )
        describe = payload["describe"]
        encoder = encoder or build_encoder(describe["encoder"] if describe["encoder"] != f"hashing-{describe['dim']}" else "hashing", dim=describe["dim"])
        if encoder.name != describe["encoder"]:
            raise ValueError(
                f"{path} was built with encoder {describe['encoder']!r}; refusing to query it "
                f"with {encoder.name!r} because the vectors would not be comparable"
            )
        passages = [Passage(**{**item, "metadata": {}}) for item in payload["passages"]]
        index = cls(encoder=encoder, passages=passages, vectors=[list(map(float, vector)) for vector in payload["vectors"]])
        index._prepare(use_faiss=use_faiss)
        return index


__all__ = [
    "INDEX_FORMAT_VERSION",
    "DenseIndex",
    "Encoder",
    "HashingEncoder",
    "SentenceTransformerEncoder",
    "build_encoder",
]
