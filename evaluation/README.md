# Evaluation

Frozen test snapshots, annotations, classical/modern comparisons, ablations, metrics, and exploratory trust study materials.

## Current real-source round

The active evaluation uses [45 frozen real release documents](real/README.md),
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
| `build_annotation_worklist.py` | Generates a stable 95-item worklist from the frozen fixture snapshot |
| `annotation-worklist.json` | 95 frozen items with record IDs, spans, and the three time fields |
| `annotation_agreement.json` | Unverified prior 94-item draft agreement; not human Cohen's kappa |
| `build_human_corpus.py` | Builds a deterministic 40-50 document human annotation candidate corpus |
| `adjudicated-qrels.template.json` | Human-only final relevance label template; not illustrative until adjudicated |
| `trust-pilot.template.json` | Human trust-pilot protocol and result placeholder |
| `human-progress.json` | Machine-readable final-evaluation completion checklist |
| `human-corpus.json` | 45 deterministic candidate documents pending human selection review |
| `entity-relation.template.json` | Human entity/relation worksheet; no synthetic labels |
| `validate_human_evaluation.py` | Refuses success until all human-only gates are complete |
| `reconcile_corpus_reviews.py` | Reconciles separate Sueda/Mehmet corpus inclusion decisions |
| `final-human-corpus.json` | Jointly approved 45-document synthetic-fixture corpus |
| `contribution-record.template.json` | Human verification record placeholder |
| `trust-pilot.protocol.json` | Trust-pilot protocol and participant/result placeholders |
| `final-human-status.json` | Overall final-evaluation completion state |

## Annotation workflow

Use the frozen snapshot rather than live collection. Two annotators must label
independently, then disagreements are adjudicated by exact span and recorded
timestamps. Do not use adjudicated labels to calculate agreement.

Each independent run is a JSON object containing an `annotations` map:

```json
{
  "annotator": "name",
  "annotations": {
    "item-001": "corroborated"
  }
}
```

To generate a stable item worklist from one frozen snapshot:

```bash
python evaluation/build_annotation_worklist.py \
  tests/fixtures/faisal/snapshot_records.jsonl \
  --out evaluation/annotation-worklist.json
```

The generated file contains record IDs, exact title/text spans, and the three
time fields. It does not assign labels; annotators must label each item
independently before Cohen's kappa is calculated.

Prepare independent input files from the worklist:

```bash
python evaluation/prepare_annotation_round.py \
  evaluation/annotation-worklist.json \
  --first-name "Annotator A" \
  --second-name "Annotator B"
```

This creates empty `not_started` files with every unique item ID listed as
pending. It does not create or guess labels. Mark each file `"status": "complete"`
only after that annotator has independently populated all shared annotations.

For a clearly marked pilot draft, Copilot can generate conservative labels
without representing them as human judgments:

```bash
python evaluation/create_copilot_annotation_draft.py \
  tests/fixtures/faisal/snapshot_records.jsonl \
  evaluation/annotation-worklist.json
```

Generated draft files must keep `"status": "simulated"` and
`"not_human_annotation": true`. They must not be supplied to the Cohen kappa
calculator as independent human annotators.

Calculate agreement only after both files contain their independent labels:

```bash
python evaluation/compute_agreement.py \
  evaluation/annotator-a.json \
  evaluation/annotator-b.json
```

For fillable human workbooks, use the CSV generator:

```bash
python evaluation/build_human_workbooks.py
```

Sueda Sen and Mehmet Aksit must fill separate evidence, entity, and relation
CSV files without seeing each other's labels. Calculate evidence agreement:

```bash
python evaluation/csv_agreement.py \
  evaluation/human-workbooks/sueda-evidence.csv \
  evaluation/human-workbooks/mehmet-evidence.csv
```

For the independent human entity/relation workbooks:

```bash
python evaluation/validate_human_annotations.py
```

Use `*-entities-work.csv` and `*-relations-work.csv` from
`evaluation/human-workbooks/`. This gate refuses success until both annotators
provide at least 200 entity mentions and 80-100 relations.

For the first human gate, both annotators fill separate corpus-review files:

```bash
evaluation/human-workbooks/sueda-corpus-review.csv
evaluation/human-workbooks/mehmet-corpus-review.csv
```

Enter `yes` or `no` in `include_in_final_corpus`. Keep the independent review
files separate until the human selection is reconciled. The corpus is complete
only after the final agreed set has 40-50 documents.

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
