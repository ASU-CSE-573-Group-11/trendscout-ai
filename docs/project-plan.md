# Project Plan and Responsibilities

This plan translates the proposal into independently testable modules connected by a shared JSON contract. Responsibilities may be rebalanced at a checkpoint without changing the research questions.

The current team has four members: Sueda Sen, Mehmet Aksit, Vidya Sagar Dudekula, and Faisal Barkat Khorasi.

## Milestones

| Dates (2026) | Deliverable | Proposed owner(s) |
|---|---|---|
| Sep 25-Oct 7 | Research scope, proposal, source policy, evaluation logic, shared JSON schema, and repository conventions | Sueda |
| Oct 8-18 | Minimal ontology, provenance model, Neo4j schema, SHACL shapes, and competency queries | Mehmet |
| Oct 19-27 | Greenhouse/Lever snapshots, GitHub snapshots, normalized roles/skills/repositories, coverage and access notes | Vidya |
| Oct 28-Nov 5 | News/company/public-voice corpus, origin clustering, BM25 baseline, frozen cohort, and weekly GitHub features plus EWMA | Sueda (corpus/BM25); Faisal (EWMA features) |
| Nov 6-13 | Dense index, query router, conversational interface, citation display, and latency logging | Faisal |
| Nov 14-Dec 2 | Temporal graph, evidence ledger, retrieval integration, ablations, and reproducible demo | Mehmet and Sueda |
| Dec 3-9 | Frozen experiments, final report, code, data notes, licenses, and contribution record | All members |

## Module responsibilities

### Sueda Sen

Research design, source strategy, corpus architecture, news/company/public-voice ingestion, YC identity freeze, origin-aware deduplication, BM25 baseline, evaluation design, and final quality checks. Coordinates proposal and final-report consistency and works on evidence-ledger decisions, evaluation, and system integration.

### Mehmet Aksit

Minimal temporal ontology, Neo4j, RDF/PROV-O export, SHACL validation, and Cypher/SPARQL competency queries. Works on graph/evidence-ledger alignment, evaluation integration, and the reproducible demo.

### Vidya Sagar Dudekula

Greenhouse/Lever collectors and GitHub snapshots; normalized job, role, skill, and repository records; coverage notes and module tests against the shared contract.

### Faisal Barkat Khorasi

Weekly GitHub activity features, EWMA baseline, dense retrieval, query routing, conversational interface, citation display, latency logging, and interface tests against the shared contract.

## Shared responsibilities

All members contribute to evaluation labeling, license and access review, result presentation, documentation, and the individual contribution record.
