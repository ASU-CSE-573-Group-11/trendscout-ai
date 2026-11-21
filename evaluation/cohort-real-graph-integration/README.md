# Cohort real-graph integration (18 companies)

Offline expansion of Mehmet's real-source semantic graph beyond the five-company mixed snapshot.

## Inputs

- `evaluation/cohort-real-graph/records.jsonl` — merged `cohort-history-v2` GitHub weeks, capped `cohort-job-history` postings, and mixed funding/investor-bearing records
- `evaluation/cohort-real-graph/workbooks/sueda-entities.csv` — Investor spans for retained mixed documents

## Artifacts

| File | Purpose |
|---|---|
| `graph.json` | Storage-neutral 18-company graph payload |
| `records.ttl` | RDF/Turtle serialization |
| `shacl-report.txt` | SHACL validation |
| `summary.json` | Counts, hashes, limitations |
| `demo-results.json` | Offline demo company summaries |
| `cited-answer-check.json` | Deterministic cited coverage checks |

## Verify

```bash
python -m evaluation.real_graph_integration check \
  --directory evaluation/cohort-real-graph \
  --out evaluation/cohort-real-graph-integration
python -m evaluation.real_graph_demo \
  --graph "$PWD/evaluation/cohort-real-graph-integration/graph.json" \
  --out "$PWD/evaluation/cohort-real-graph-integration/demo-results.json"
```

Live Neo4j load is optional and uses the same `graph.neo4j` path as the mixed demo.
