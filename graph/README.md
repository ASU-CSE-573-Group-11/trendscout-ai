# Graph

Neo4j loading, entity resolution, evidence-ledger integration, Cypher queries, and graph-path tests.

## Initial import contract

[`import_contract.py`](./import_contract.py) converts validated source records
into deterministic graph payloads without requiring a live Neo4j instance.
Every `SourceRecord` retains the source URL, exact passage, three collection
clocks, content hash, collector version, and `origin_cluster_id`.

The first relationships are:

```text
(SourceRecord)-[:ABOUT]->(Startup)
(SourceRecord)-[:PUBLISHED_BY]->(Publisher)
(SourceRecord)-[:MEMBER_OF_ORIGIN]->(OriginCluster)
```

The payload is intentionally storage-neutral so the Neo4j loader, RDF/PROV-O
export, and SHACL validation can consume the same contract.

## Database and validation artifacts

- [`constraints.cypher`](./constraints.cypher) defines idempotent Neo4j
  uniqueness constraints and temporal lookup indexes.
- [`../ontology/shapes.ttl`](../ontology/shapes.ttl) defines the first SHACL
  shapes for source-record provenance, startup identity, and publisher identity.

The constraints must be applied before loading records. SHACL validation remains
an explicit step after RDF export; the repository does not require a live
Neo4j server or SHACL engine for its unit tests.

The expanded ontology declares startup, investor, funding-round, public-voice,
product, technology, skill, job-posting, and repository concepts with explicit
property domains and ranges. Five independently executable SPARQL 1.1
competency queries are in [`sparql/`](./sparql/README.md). Tests parse every
query and execute representative provenance, funding-to-listing, and
technology/skill paths against an in-memory RDF graph.

## Live Neo4j loader

Start the local Community Edition database:

```bash
docker compose up -d neo4j
python -m pip install -r requirements-interface.txt
```

Load a validated JSONL snapshot:

```bash
python -m graph.neo4j artifacts/collectors/RUN_ID/records.jsonl
```

To load claim/evidence projections too:

```bash
python -m graph.neo4j artifacts/collectors/RUN_ID/records.jsonl \
  --evidence artifacts/evidence.jsonl
```

To load the complete real semantic graph (claims, investors, funding rounds,
public job listings, repositories, skills, and technologies):

```bash
python -m graph.neo4j \
  --graph-payload evaluation/mixed/real-graph-integration/graph.json
```

The complete-payload loader applies the same constraints, uses parameterized
Cypher for every node and edge, and reports database label counts after import.
The checked-in payload is independently replayed from the frozen mixed records
with `python -m evaluation.real_graph_integration check`.

Run the deterministic demo offline, or compare it with the exact payload stored
in the local Neo4j database:

```bash
python -m evaluation.real_graph_demo
python -m evaluation.real_graph_demo --live
```

The demo reports per-company observed claims, funding announcements, public job
postings, repositories, skills, and technologies. Its output explicitly avoids
converting listings into hires or temporal co-occurrence into causality.

To view the checked-in dashboard:

```bash
cd evaluation/mixed/real-graph-integration
python -m http.server 8770 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8770/demo.html`.

The complete environment setup, offline replay, Neo4j load, live parity check,
dashboard launch, test commands and troubleshooting guide are in
[`../evaluation/mixed/real-graph-integration/README.md`](../evaluation/mixed/real-graph-integration/README.md).

The loader applies `constraints.cypher`, executes the parameterized import
statements, and verifies the `SourceRecord` node count. Override the local
defaults with `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, or
`NEO4J_DATABASE`.

The first live check loaded 95 fixture records as 94 distinct source nodes,
applied the Neo4j constraints, and returned live independent-origin results.
Claim/evidence JSONL is loaded through `--evidence` and creates
`Claim` nodes plus `SUPPORTS` relationships.

[`cypher.py`](./cypher.py) builds parameterized import statements from the
storage-neutral graph payload. It does not open a database connection and uses
the same validated records as the graph contract. The initial competency
queries are in [`competency_queries.cypher`](./competency_queries.cypher).

[`evidence.py`](./evidence.py) defines the claim/evidence handoff. It requires
an explicit claim text and evidence state, derives a stable claim id, and keeps
the supporting record, origin, passage hash, and three source-record clocks.
It does not infer claims from text automatically.

Evidence-ledger review queries are in
[`evidence_queries.cypher`](./evidence_queries.cypher). They keep support
counts origin-aware and expose the observed-time window used for review.

Temporal multi-hop queries are in
[`temporal_queries.cypher`](./temporal_queries.cypher). They connect startups,
source records, and claims while enforcing observation windows and minimum
independent-origin thresholds.

[`rdf.py`](./rdf.py) exports the same graph payload as RDF/Turtle with
PROV-O-compatible `SourceRecord` and `Publisher` types. The exporter validates
temporal literals and preserves source URLs, passages, hashes, and origin
clusters.

[`shacl.py`](./shacl.py) runs the repository SHACL shapes against the exported
RDF graph. A validation result includes the boolean conformance value, the
machine-readable report graph, and the human-readable report text.
