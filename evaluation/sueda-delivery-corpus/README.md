# Frozen documentary source corpus

Collected on 20 November 2026 (America/Phoenix). The full feed snapshot has
584 records: 565 company documents, two news records, six public-voice records,
and 11 unverified cohort-registry assertions. Fifteen public-voice feeds were
curated; fetched-feed, unavailable-feed, and retained-match counts are distinct
in `manifest.json` and `coverage.json`. A successful feed can have zero cohort
matches. Original failed requests retain their HTTP failure notes.

`sources/` preserves decoded public RSS/Atom text, hashed as UTF-8.
`cohort.json` and `named_sources.json` freeze the collection configuration;
`endpoint-revision.json` documents corrected current URLs. Cohort membership
and identifiers are unchanged. `records.jsonl` preserves publication and
observation times separately. Registry assertions have no publication/event
date and are not verified YC directory evidence.

`study-records.jsonl` contains the 136 documents dated 1 November 2025 through
20 November 2026: 135 company documents and one news record. Voice matches in
the full archive are older and are not current evidence for this slice.
`delivery-summary.json` records these populations. Publication-time availability
does not prove that a document had been observed at the earlier cohort freeze.

`bm25-demo.json` contains five origin-aware smoke queries, source URLs, and
scores over the study slice. No human relevance or answer-accuracy score is
claimed for those queries. These collection outputs complement, rather than
replace, the frozen release and mixed-source experiments.

```bash
.venv/bin/python -m collectors.snapshot replay --directory evaluation/sueda-delivery-corpus
.venv/bin/python -m evaluation.verify_sueda_delivery
```

This is a local coursework cache of public feeds. Publisher content retains its
original rights; public accessibility is not a redistribution license. Review
source terms before redistributing raw bodies. Code dependencies and their
licenses are documented in `docs/source-policy.md` and module READMEs.
