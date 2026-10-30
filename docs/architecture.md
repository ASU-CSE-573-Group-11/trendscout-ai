# Architecture and Module Contracts

## Design principle

TrendScout AI treats claims, time, and evidence as first-class objects. A generated answer must be traceable to dated evidence records and must expose uncertainty when the available evidence is incomplete or contradictory.

## End-to-end pipeline

1. **Collect:** obtain permitted public signals from news and company sources, Greenhouse/Lever job boards, GitHub, and selected public voices.
2. **Normalize:** convert every observation to the shared source-record schema in `schemas/record.schema.json`.
3. **Deduplicate:** group exact and near-duplicate records so syndicated copies do not count as independent corroboration.
4. **Extract:** identify entities, events, relations, claims, and supporting text passages.
5. **Resolve and validate:** align aliases, check ontology constraints, and preserve provenance and temporal fields.
6. **Store and index:** load structured claims into the temporal graph and passages into lexical and dense indexes.
7. **Retrieve:** combine Cypher traversal, BM25, and dense retrieval according to the query type and time window.
8. **Answer:** return a cited response with an evidence state and graph path, or explicitly report insufficient evidence.

## Component boundaries

| Component | Expected input | Expected output |
|---|---|---|
| Collectors | Source configuration and collection date | Valid source records with `origin_cluster_id` |
| Extraction | Source records and passages | Candidate entities, events, and claims |
| Ontology/validation | Candidate graph objects | Validated RDF/graph objects and SHACL report |
| Graph | Validated entities, relations, and claims | Neo4j graph and reproducible query results |
| Retrieval | User question, time window, and indexes | Ranked passages and graph paths |
| Interface | Retrieved evidence bundle | Cited answer, evidence state, or abstention |
| Evaluation | Frozen snapshot and test questions | Metrics, errors, ablations, and latency report |

The first handoff boundary is [`retrieval/handoff.py`](../retrieval/handoff.py).
It validates frozen `records.jsonl` snapshots, exposes origin-aware lexical
retrieval, and projects records into graph evidence without discarding source,
provenance, or temporal fields.

## Pilot-first acceptance test

Before expanding to the full cohort, one startup must pass through the entire pipeline. The pilot is accepted when:

- records validate against the shared JSON schema;
- repeated collection does not inflate duplicate counts;
- every accepted claim links to a source passage and observation time;
- at least one temporal, multi-hop question returns a correct evidence path;
- a deliberately unsupported question produces an explicit abstention;
- the pilot can be replayed from a frozen snapshot.
