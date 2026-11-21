# Ontology

Temporal ontology, RDF/Turtle export, PROV-O mapping, and SHACL validation artifacts.

[`trendscout.ttl`](./trendscout.ttl) defines the shared vocabulary for startups,
source records, publishers, claims, events, documents, provenance, origin
clusters, and the three source-record clocks:

- `eventAt`
- `publishedAt`
- `observedAt`

The vocabulary also defines the research-domain classes `Investor`, `Voice`,
`Product`, `Technology`, `Skill`, `JobPosting`, `Repository`, and
`FundingRound`. Project object and datatype properties declare explicit RDFS
domains and ranges. These declarations support validation and querying; they do
not turn a public listing into proof of a hire, funding causality, or a semantic
claim.

[`shapes.ttl`](./shapes.ttl) now validates the minimum provenance fields for
`SourceRecord`, plus stable identity fields for `Startup` and `Publisher`.

The Python RDF exporter in [`../graph/rdf.py`](../graph/rdf.py) uses these
namespaces and emits Turtle for downstream SHACL validation or RDF/Turtle
interoperability checks.

Independent SPARQL 1.1 competency queries are documented under
[`../graph/sparql/`](../graph/sparql/README.md).

SHACL execution is provided by [`../graph/shacl.py`](../graph/shacl.py); shape
failures are intended to block graph import rather than be silently ignored.
