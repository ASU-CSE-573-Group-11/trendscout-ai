from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25Index:
    """Okapi BM25 over source-record titles and passages. No external ranker dependency."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.records: list[dict[str, Any]] = []
        self.doc_tokens: list[list[str]] = []
        self.doc_len: list[int] = []
        self.df: dict[str, int] = defaultdict(int)
        self.avgdl = 0.0

    @classmethod
    def from_records(cls, records: Iterable[dict[str, Any]], **kwargs: float) -> "BM25Index":
        index = cls(**kwargs)
        index.fit(list(records))
        return index

    def fit(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.doc_tokens = []
        self.doc_len = []
        self.df = defaultdict(int)
        for record in records:
            tokens = tokenize(f"{record.get('title') or ''} {record.get('text') or ''}")
            self.doc_tokens.append(tokens)
            self.doc_len.append(len(tokens))
            for term in set(tokens):
                self.df[term] += 1
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0

    def _idf(self, term: str) -> float:
        n = len(self.records)
        df = self.df.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, k: int | None = 5) -> list[dict[str, Any]]:
        query_tokens = tokenize(query)
        scores: list[tuple[float, int]] = []
        for index, tokens in enumerate(self.doc_tokens):
            tf = Counter(tokens)
            score = 0.0
            doc_len = self.doc_len[index] or 1
            for term in query_tokens:
                if term not in tf:
                    continue
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * doc_len / (self.avgdl or 1))
                score += self._idf(term) * (freq * (self.k1 + 1)) / denom
            scores.append((score, index))
        scores.sort(reverse=True)
        hits = []
        ranked = scores if k is None else scores[:k]
        for score, index in ranked:
            if score <= 0:
                continue
            record = self.records[index]
            hits.append(
                {
                    "score": score,
                    "record_id": record["record_id"],
                    "origin_cluster_id": record["origin_cluster_id"],
                    "record": record,
                }
            )
        return hits
