# Mixed-source evaluation round

Frozen on 20 November 2026 (America/Phoenix). This follow-up preserves the
original 18-company cohort and all 28 question texts. It extends observation
beyond the original 30 October freeze; it must not be presented as evidence
that was available at that earlier date.

## Corpus and source records

The 45 records contain three primary funding announcements (LangChain,
LlamaIndex, Browserbase), 18 currently listed jobs (LangChain/LlamaIndex), and
eight complete ISO weeks of default-branch commits for each of LangChain,
CrewAI, and Langfuse. `manifest.json` records selection and source checksums.
`sources/` retains the funding pages, full public job-board responses, and
GitHub snapshots with personal profiles/messages removed. Job selection uses
explicit target-skill counts and URL tie-breaking before any retrieval run.

Weekly observations share repository origins. They are not 24 independent
documents. GitHub observation time stays at collection time; the activity
window is reconstructed from actual commit timestamps. Historical stars,
forks, and issue counters remain unknown. Funding event dates are not inferred
from publication dates. Job publication dates are not assumed to be first
hiring dates, and a current board cannot establish historical job closures or
an increase in hiring.

## Executed integration

- Four retrieval conditions × 28 questions: 112 saved answers in `answers/`.
- Three hybrid ablations × 28 questions: 84 saved answers in `integration/`.
- 1,260 evidence-component judgments, with an exact quote for every positive.
- 374 exact-offset entity predictions and 374 `MENTIONS` relation predictions.
- 45 source excerpts in the evidence ledger, 124 graph nodes, 180 edges, RDF
  export, and a conforming SHACL report.

`integration/source-inclusion-review.csv` records a source-based inclusion
decision for each record. It does not impersonate either team reviewer.
`integration/annotation-record-search.json` records the search across 18 local
and cached remote refs, historical label files, and nearby project files.
Legacy JSON labels cover at most 94 shared items. No completed entity/relation
CSV label set was located. No remote refs were refreshed during that search.

The frozen candidate workbooks have 276 entity candidates and 108 relation
candidates per annotator. The separate extraction inventory has 374 exact
lexicon matches across complete passages; these are predictions requiring
review, not independently annotated gold labels. The two candidate sets serve
different purposes and must not be silently merged after labelling.

## Interpretation

Ten original questions have at least one explicit evidence component.
`integration/component-qrels.json` uses a documented deterministic rubric:
0 means no matching component, 1 means an explicit component. No grade 2 is
assigned. These diagnostics are not the strict full-question relevance labels
used by the earlier release-only study, so scores are not directly comparable.
They do not establish full answerability, growth, a causal funding-to-hiring
path, or temporal answer accuracy.

| Raw document retriever | P@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.1643 | 0.2032 | 0.2262 | 0.5155 |
| Hashing (`dense`) | 0.1786 | 0.2190 | 0.2946 | 0.6164 |
| Hybrid | 0.1714 | 0.2055 | 0.2321 | 0.5485 |

P@5/MRR average over all 28 questions; recall/nDCG exclude the 18 questions
without positive component records. Rankings collapse shared documentary
origins, so repeated weeks from one repository cannot fill the result list.
Runs use lexical hashing, an extractive provider, and an in-memory graph.
Automatic support flags are bookkeeping, not semantic correctness ratings.
No graph performance advantage or primary research success is established.

## Reproduction and agreement

Existing frozen outputs are preserved. For a new collection use a new path:

```bash
.venv/bin/python evaluation/collect_mixed_corpus.py --out evaluation/mixed-new
.venv/bin/python evaluation/real_round.py prepare --directory evaluation/mixed-new --relation-candidates-per-document 4
.venv/bin/python evaluation/real_round.py run --directory evaluation/mixed-new
.venv/bin/python -m evaluation.integrate_mixed_round --directory evaluation/mixed-new
```

To complete agreement on this frozen round, populate both independent
`workbooks/{sueda,mehmet}-{entities,relations}.csv` files using the exact frozen
candidate IDs and allowed labels. Use `NONE` for rejected candidates. Each
annotator needs 200+ accepted entities and 80–100 accepted relations. Record
completion, snapshot/workbook hashes, and independence in that annotator's
attestation file, then run:

```bash
.venv/bin/python evaluation/real_round.py agreement --directory evaluation/mixed
.venv/bin/python evaluation/real_round.py validate --directory evaluation/mixed
```

`integration/agreement-status.json` retains a null kappa until the required
inputs exist. Corpus decisions by both reviewers, pilot measurements, and
contribution verification also remain separate completion requirements. The final
validator additionally requires adjudicated full-question qrels; the completed
component-only diagnostic deliberately does not satisfy that requirement.

## Corpus first-review update

The existing source-inclusion decisions have been transferred into the
`sueda_include` column of `workbooks/corpus-review.csv` for all 45 frozen
records. `integration/corpus-first-review.json` binds the source decisions and
worksheet to the snapshot. This is one project source review; Mehmet's
independent decisions, final inclusion and adjudicator fields remain unfilled.
The release and mixed corpora are different source sets and their labels are
not interchangeable. `evaluation/study-index.json` identifies the annotation,
pilot, retrieval and documentary-collection scopes explicitly.
