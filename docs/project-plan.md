# Project Plan and Responsibilities

This plan translates the proposal into independently testable modules connected by a shared JSON contract. Responsibilities may be rebalanced at a checkpoint without changing the research questions.

## Milestones

| Dates (2026) | Deliverable | Proposed owner(s) |
|---|---|---|
| Sep 25-Oct 7 | Research scope, proposal, source policy, evaluation logic, shared JSON schema, and repository conventions | Sueda |
| Oct 8-18 | Minimal ontology, provenance model, Neo4j schema, SHACL shapes, and competency queries | Mehmet |
| Oct 19-27 | Greenhouse/Lever snapshots, normalized roles and skills, coverage and access notes | Vidya |
| Oct 28-Nov 5 | GitHub activity collector, weekly features, EWMA baseline, and repository-quality flags | Baaz |
| Nov 6-13 | Dense index, query router, conversational interface, citation display, and latency logging | Faisal |
| Nov 14-Dec 2 | Temporal graph, evidence ledger, retrieval integration, ablations, and reproducible demo | Mehmet and Sueda |
| Dec 3-9 | Frozen experiments, final report, code, data notes, licenses, and contribution record | All members |

## Module responsibilities

### Sueda Sen

Research design, source strategy, corpus architecture, news/company/public-voice ingestion, deduplication, BM25 baseline, evaluation design, and final quality checks. Coordinates proposal and final-report consistency and works on evidence-ledger decisions, evaluation, and system integration.

### Mehmet Aksit

Minimal temporal ontology, Neo4j, RDF/PROV-O export, SHACL validation, and Cypher/SPARQL competency queries. Works on graph/evidence-ledger alignment, evaluation integration, and the reproducible demo.

### Vidya Sagar Dudekula

Greenhouse/Lever collectors and normalized job, role, and skill snapshots, including coverage notes and module tests against the shared contract.

### Baaz Jhaj

GitHub collector, weekly activity features, EWMA baseline, repository-quality controls, and module tests against the shared contract.

### Faisal Barkat Khorasi

Dense retrieval, query routing, conversational interface, citation display, latency logging, and interface tests against the shared contract.

## Shared responsibilities

All members contribute to evaluation labeling, license and access review, result presentation, documentation, and the individual contribution record.
