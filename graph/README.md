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
