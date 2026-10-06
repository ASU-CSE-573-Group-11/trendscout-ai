# TrendScout AI — Group 11

TrendScout AI is a CSE 573 Semantic Web Mining project that combines public startup signals with a temporal knowledge graph and evidence-aware conversational retrieval.

## Project scope

- Study a focused cohort of 15–20 AI startups in agent infrastructure and developer tools.
- Collect public news, company announcements, job postings, and GitHub activity.
- Normalize records through a shared JSON contract.
- Represent claims, timestamps, provenance, and evidence status in a temporal knowledge graph.
- Compare classical baselines with modern retrieval and extraction methods.
- Return cited answers or explicitly report insufficient evidence.

## Repository structure

- `collectors/` — independent news, jobs, and GitHub collection modules
- `schemas/` — shared JSON records and validation contracts
- `ontology/` — ontology, RDF/PROV-O, and SHACL files
- `graph/` — Neo4j loading and graph-query code
- `retrieval/` — BM25, dense retrieval, and query routing
- `interface/` — conversational interface and citation display
- `evaluation/` — test sets, metrics, baselines, and ablations
- `data/` — local data layout; raw datasets are not committed by default
- `docs/` — project decisions, source policy, and contribution notes

## Initial workflow

1. Finalize scope and source policy.
2. Approve the shared JSON schema.
3. Create one-startup pilot records.
4. Validate the first graph and retrieval path.
5. Expand only after the end-to-end pilot works.

## Data and access rules

- Use documented APIs, RSS feeds, and permitted public pages.
- Do not collect applicant data, private profiles, credentials, or restricted content.
- Store source URL, publisher, retrieval time, event/publication time, and content hash.
- Do not commit API keys, tokens, secrets, or large raw datasets.
- Record third-party licenses and clearly distinguish team-authored code.

