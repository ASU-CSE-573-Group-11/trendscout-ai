# Retrieval

BM25 and dense indexes, temporal hybrid retrieval, and query-routing components.

## Sueda Sen — BM25 baseline

`retrieval/bm25.py` indexes `title` plus `text` from accepted source records. It is the classical lexical baseline for later comparison with Faisal's dense index and Mehmet's Cypher retrieval.

```python
from retrieval.bm25 import BM25Index

hits = BM25Index.from_records(records).search("LangSmith Engine", k=5)
```

Returned hits keep `record_id` and `origin_cluster_id` so evaluation can count independent origins rather than duplicate pages.

## Frozen snapshot handoff

`retrieval/handoff.py` provides the boundary between Sueda's accepted `records.jsonl`
snapshot and downstream graph/retrieval work:

```python
from pathlib import Path
from retrieval.handoff import graph_evidence, load_records_jsonl, search_snapshot

records = load_records_jsonl(Path("data/processed/sueda/records.jsonl"))
hits = search_snapshot(records, "LangSmith hiring", k=5)
evidence = graph_evidence(records[0])
```

The loader validates every record against the shared schema. `search_snapshot`
returns at most one hit per `origin_cluster_id` by default, preventing syndicated
copies from crowding a result set. `graph_evidence` preserves the source URL,
passage, three time fields, content hash, and origin cluster needed for provenance.

## Faisal Barkat Khorasi - dense retrieval, fusion, and routing

`retrieval/dense.py` indexes the same unit BM25 does, one passage per record
(title plus text), so the two rankings are comparable. The default encoder is a
deterministic hashing encoder that needs no model download; it is **lexical,
not semantic**, and results produced with it should be reported as a second
lexical baseline rather than as dense retrieval. Install
`requirements-interface.txt` for the real `all-MiniLM-L6-v2` encoder. The index
persists beside the frozen snapshot and refuses to load under a different
encoder.

`retrieval/hybrid.py` fuses BM25 and dense hits by reciprocal rank
(`score = sum(weight / (k + rank))`, `k = 60`). Rank fusion needs no score
calibration and no labels, which suits a snapshot with no relevance judgements
yet. `bm25.py` is used unmodified; only its input is prepared.

```python
from retrieval.hybrid import HybridRetriever, RetrievalConfig

retriever = HybridRetriever.from_records(records)
hits = retriever.search("LangSmith evaluation", k=5)
bm25_only = retriever.search("LangSmith evaluation", k=5, config=RetrievalConfig(mode="bm25"))
```

`retrieval/timewindow.py` resolves relative expressions against the snapshot
date, never against today, so a frozen snapshot answers "the last eight weeks"
the same way next month.

`retrieval/router.py` sends exact and aggregate questions to Cypher, narrative
questions to documents, and mixed temporal questions to both, using either
ordered intent rules or the proposal's TF-IDF logistic baseline. A question
about a period after the snapshot, or before collection began, is routed to
abstention before any retrieval runs.

`retrieval/graph_queries.py` loads Mehmet's `graph/*.cypher` as named templates,
and `retrieval/graph_access.py` answers them over the shared graph payload so
the demo replays a frozen snapshot without a database. Both leave `graph/`
untouched.

The conversational interface is in [`interface/`](../interface/README.md).
Details and first numbers: [`docs/faisal-trends-and-retrieval.md`](../docs/faisal-trends-and-retrieval.md).
