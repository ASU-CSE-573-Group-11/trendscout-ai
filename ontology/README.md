# Ontology

Minimal temporal ontology, RDF/Turtle export, PROV-O mapping, and SHACL validation artifacts.

[`trendscout.ttl`](./trendscout.ttl) defines the first shared vocabulary for
startups, source records, publishers, claims, events, documents, provenance,
origin clusters, and the three source-record clocks:

- `eventAt`
- `publishedAt`
- `observedAt`

The vocabulary is deliberately small for the first graph handoff. Claims,
events, SHACL shapes, and Neo4j-specific constraints will be added in the next
graph commits.
