# SPARQL competency queries

Each `.rq` file contains one SPARQL 1.1 query and can be executed independently.
The variables named in the leading comment are runtime bindings; callers should
provide RDF literals with the datatypes used by the ontology.

- `startup_evidence.rq` returns provenance-bound source observations in a UTC
  interval.
- `claim_independent_origins.rq` counts distinct origin clusters rather than
  syndicated copies.
- `funding_to_hiring.rq` returns temporally ordered funding and public job-listing
  observations. It does not infer completed hires or causality.
- `technology_skill_demand.rq` connects public job postings to normalized
  technologies and skills.
- `repository_claim_provenance.rq` exposes repository and documentary evidence
  paths without treating repository activity as semantic claim proof.

The repository tests parse all five files with RDFLib and execute representative
queries against a deterministic in-memory graph.
