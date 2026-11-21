# Evaluation

Frozen test snapshots, annotations, classical/modern comparisons, ablations, metrics, and exploratory trust study materials.

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

Calculate agreement only after both files contain their independent labels:

```bash
python evaluation/compute_agreement.py \
  evaluation/annotator-a.json \
  evaluation/annotator-b.json
```

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
