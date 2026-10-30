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

Dense retrieval, query routing, and the conversational interface remain Faisal's module.
