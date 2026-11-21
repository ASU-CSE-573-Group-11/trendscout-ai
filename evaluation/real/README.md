# Real-document evaluation round

Frozen on 20 November 2026 (America/Phoenix). The collection timestamp is
2026-11-21T06:14:33Z. This is a separate round from the legacy fixture workbooks.

45 public release documents: 15 each from LangChain, LlamaIndex, and CrewAI.
`manifest.json` records the exact API responses, selected release IDs, and hashes.
`records.jsonl` contains complete normalized release bodies. `sources/` preserves
raw API responses. The `company` record type denotes first-party documents;
`github` is reserved for activity-window observations by the signal pipeline.
Release publication is the release event time; observation time is separate.

The scope is narrower than the full project: release notes cannot establish
funding, hiring, activity growth, or independent corroboration. The original
28 questions are frozen verbatim in `questions.json`. Their expected behaviors
were designed for the original study, so they are diagnostic here; this round
cannot establish the original temporal multi-hop success criterion.

## Completed source review and scoring

Source-reviewed qrels and scores are now available without filling the separate
team-adjudication workbook. The original 28 questions have 1,260 graded pairs:
no release note establishes the hiring, funding, growth, or ledger facts they
ask for, so P@5/MRR are zero and recall/nDCG are undefined for zero-positive
questions. This is an observed corpus-coverage result.

`release-study/` holds a separate 28-question known-release fact lookup study,
its frozen answer key, 1,260 judgments, and 112 additional saved answer bundles.
Questions and judgments were authored before retrieval on this set. Every
positive judgment carries an exact source quote. Reviewer provenance is
`Codex source review`; no independent team adjudication is asserted.

```bash
# Raw document ranking measurements, independent of answer citations.
.venv/bin/python evaluation/real_round.py rank --qrels evaluation/real/source-reviewed-qrels.json
.venv/bin/python evaluation/real_round.py rank --study-directory evaluation/real/release-study --qrels evaluation/real/release-study/source-reviewed-qrels.json
# Score the four saved answer/citation conditions.
.venv/bin/python evaluation/real_round.py score --qrels evaluation/real/source-reviewed-qrels.json
.venv/bin/python evaluation/real_round.py score --study-directory evaluation/real/release-study --qrels evaluation/real/release-study/source-reviewed-qrels.json
```

`retrieval-metrics.json` records actual retriever top-5 rankings.
`scored-metrics.json` uses unique record IDs in answer citation order; these are
separate measurements. The graph-only condition emits structured query results
and is included in answer/citation scoring, not misrepresented as a document
retriever. Hashing is a lexical baseline, not semantic dense retrieval.

With one relevant record per release question, maximum P@5 is 0.2.
BM25 and hybrid retrieve 27/28 targets; hashing retrieves 23/28. All per-question
ranks and scores are saved. These results do not establish temporal multi-hop
success or independent agreement.

## Independent annotations

Use `workbooks/sueda-entities.csv`, `mehmet-entities.csv`, `sueda-relations.csv`,
and `mehmet-relations.csv`. There are 418 shared exact mention candidates and
126 shared document/mention relation candidates. These are candidates, not
accepted annotations. Labels are blank. Offsets are Python character offsets
into the normalized record text; end is exclusive. A relation's subject is its
source document ID and its object is the candidate mention.

Work separately without sharing labels. Fill `label` using `guidelines.json`,
or `NONE` to reject a candidate. Each annotator must accept 200+ entity mentions
and 80–100 relations; all candidates, including rejections, must be labelled.
The fixed candidates permit categorical agreement on the same items. This
measures classification agreement on candidates, not free-span detection recall.
For additional mentions or different relation pairs, freeze a new common
candidate list before either annotator labels it. Do not align after adjudication.

After completing independent labels, fill each person's attestation: `status`
`complete`, `method` `human`, `independent` true, actual `completed_at`, and
`workbook_sha256.entities` / `.relations` using the actual file hashes:

```bash
shasum -a 256 evaluation/real/workbooks/sueda-entities.csv
shasum -a 256 evaluation/real/workbooks/sueda-relations.csv
shasum -a 256 evaluation/real/workbooks/mehmet-entities.csv
shasum -a 256 evaluation/real/workbooks/mehmet-relations.csv
.venv/bin/python evaluation/real_round.py agreement
```

The calculation uses every shared candidate, including NONE. Single-category
kappa is undefined. Disagreements are listed; adjudication must be saved separately
and must never replace independent inputs. Attestations document the annotators'
statements; software cannot establish that people actually worked independently.

## Corpus review and qrels

Complete `workbooks/corpus-review.csv` with both inclusion decisions, final
selection, adjudicator, and notes. An exclusion requires a new frozen round and
new retrieval outputs. Existing scored input must not be silently changed.

`workbooks/qrels.csv` contains all 28 × 45 = 1,260 question/document pairs,
without retrieval rankings. Grade each independently, then adjudicate:
0 = irrelevant or does not support the question; 1 = partial relevant evidence;
2 = direct relevant evidence. Zero-positive questions are allowed. Fill
`sueda_grade`, `mehmet_grade`, `final_grade`, `adjudicator`, and a short `notes`
rationale. Read the record body by `record_id`, including timestamps; a matching
company name alone does not establish relevance.

```bash
.venv/bin/python evaluation/real_round.py score
```

Without `--qrels`, this optional team-adjudication path exports
`adjudicated-qrels.json` and `scored-metrics.json` only with complete judgments. Scores must use the saved answers, snapshot and questions. Answer bundles are
losslessly compressed as `answers/*.jsonl.gz`; the metric loader reads them directly. Unjudged
retrieval and citation precision stay null in `unjudged-metrics.json`.

## Trust pilot and contribution verification

`trust-pilot.json` defines six frozen tasks, two conditions and required result
fields. Record 5–8 consenting participants using pseudonymous IDs, six unique
tasks each, three per condition, actual presentation order, correctness,
duration, and confidence. Counterbalance condition order across participants.
Fill the adjudicated task key before judging responses. Preserve each task's
presented answer/citations as study evidence. Do not treat the four team member
names as pilot participants without actual participation records.

`contribution-record.json` names the four project members and records relevant
repository commits with their actual authors and changed paths. Confirm the
graph-author identity mapping and add completed human evaluation tasks with
verification references per member before setting status to `verified`.
The user's completion statement is recorded separately from measured evidence.

```bash
.venv/bin/python evaluation/real_round.py validate
```

Exit 1 means required records or results are missing. Existing human input is
never overwritten by `prepare`; `run` refuses to replace a completed run.
For a new round use a new directory with `collect_real_corpus.py --out PATH`,
then `real_round.py prepare --directory PATH` and `run --directory PATH`.

The current `dense` run uses hashing, a second lexical baseline. Do not present
it as a semantic dense model. The provider is extractive and the graph backend
is in memory; times describe local execution only.
