# Evaluation

Frozen test snapshots, annotations, classical/modern comparisons, ablations, metrics, and exploratory trust study materials.

## Current mixed-source follow-up

The [mixed-source round](mixed/README.md) includes funding, jobs, and weekly
GitHub observations with all 28 original questions. It has 196 saved answers
across four conditions and three ablations, source-linked extraction outputs,
and graph/RDF/SHACL integration. Independent annotation agreement remains
uncomputed. Component-only relevance scores do not establish temporal accuracy.

## Historical release-source round

The earlier evaluation uses [45 frozen real release documents](real/README.md),
not the historical fixture workbooks described below. Run
`python evaluation/real_round.py validate` for its completion gates. The legacy
files remain available for reproducibility; their labels and approvals do not
transfer to the real corpus. See [the evidence-based report](../docs/final-report.md).

## Sueda Sen — evaluation design

The first complete retrieval set contains 28 questions: temporal multi-hop,
evidence-state, and insufficient-evidence cases. The questions are frozen before
scoring. Additions require a documented revision and must not change an existing
question identifier or its expected behavior.

| File | Purpose |
|---|---|
| `questions.seed.json` | Final retrieval set, abstention cases, metric names, and success thresholds |
| `annotation_guidelines.json` | Entity/relation types, span rule, and the three clocks |
| `compute_agreement.py` | Cohen's kappa calculation for independent annotator labels |
| `real_round.py` | Reproducible real-document corpus, scoring, and human-agreement runner |
| `real/` | Frozen real release corpus, workbooks, metrics, pilot session, and report |
| `mixed/` | Reproducible mixed-source follow-up and integration diagnostics |
| `submission/` | Submission audit, readiness, contribution and verification artifacts |

## Real and mixed evaluation workflow

Use the real-document round for the primary active evaluation:

```bash
.venv/bin/python evaluation/real_round.py rank \
  --qrels evaluation/real/source-reviewed-qrels.json
.venv/bin/python evaluation/real_round.py score \
  --qrels evaluation/real/source-reviewed-qrels.json
.venv/bin/python evaluation/real_round.py validate
```

The separate `mixed/` round is an integration diagnostic. It does not replace
independent annotation or temporal-answer correctness.

Primary success, from the proposal: temporal multi-hop accuracy above the strongest non-graph baseline, unsupported claims below 10%, and valid evidence for at least 90% of factual answer claims.

Do not mix a live collection run with a scored evaluation snapshot.

## Faisal Barkat Khorasi — scoring the answer bundles

`metrics.py` and `run_metrics.py` score the answer bundles the interface emits.
They are scaffolding for the row above, not a change to its design: the labels,
thresholds, and interpretation stay with the evaluation owner.

```bash
# One bundle file per retrieval condition.
for mode in hybrid bm25 dense graph_only; do
  python -m interface --demo --seed-questions --mode $mode --out artifacts/answers-$mode.jsonl
done

python evaluation/run_metrics.py artifacts/answers-*.jsonl
python evaluation/run_metrics.py artifacts/answers-*.jsonl --qrels evaluation/qrels.example.json
```

Computed **without** labels, from the bundle alone: abstention accuracy against
`expected_behavior`, claim-support rate, unsupported-claim rate, and median and
p90 latency, each checked against the success thresholds in
`questions.seed.json`.

Needing labels: Precision@k, Recall@k, MRR, nDCG@k, and citation precision.
Without a `--qrels` file these print as `n/a` rather than `0`, so an unscored
run cannot be mistaken for a scored one.

`qrels.example.json` documents the label format and is marked
`"illustrative": true`, because its grades were derived from one run's own
citations and are therefore circular. The runner prints a loud banner when a
label file carries that flag. Replace it with adjudicated judgements before
reporting anything.

Trend ranking (`--trend-signals` plus `--trend-rubric`) scores Precision@k and
the false-alert rate against a weekly rubric of genuinely trending entities.

## Source history and separate independent review

Replay the latest public posting history with
`python -m evaluation.ats_history --check`. The source-bound artifact is
`evaluation/cohort-ats-history/review.json`; coverage is 12/18 companies.
Historical counts use archived payloads, not live rendering of past pages.

Run `python -m evaluation.independent_review serve --port 8767` and open
<http://127.0.0.1:8767>. Choose your own identity and the frozen round. Read the
source, select a label and save. Decisions persist in separate reviewer files
under `evaluation/independent-review/<round>/direct/`; existing assisted CSVs are preserved.
The session statement concerns personal independent source decisions, not another
team authorization request. No label is preselected. After both reviews are
complete, run `python -m evaluation.independent_review agreement --round real`
(or `--round mixed`). The command verifies source hashes and complete candidate
coverage and returns agreement and disagreements without adjudicating them.
Independence is reviewer self-reported. No study decisions were generated while
testing this console.

The release console uses the expanded frozen v2 pool: 776 entity candidates and
100 relation candidates. The mixed pool has 276 entities and 108 relations.
Assisted JSON files outside the `direct` subdirectory are retained separately
and do not count toward independent-review completion.
