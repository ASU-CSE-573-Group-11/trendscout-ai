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

[`shapes.ttl`](./shapes.ttl) now validates the minimum provenance fields for
`SourceRecord`, plus stable identity fields for `Startup` and `Publisher`.

The Python RDF exporter in [`../graph/rdf.py`](../graph/rdf.py) uses these
namespaces and emits Turtle for downstream SHACL validation or RDF/Turtle
interoperability checks.
