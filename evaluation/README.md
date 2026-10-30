# Evaluation

Frozen test snapshots, annotations, classical/modern comparisons, ablations, metrics, and exploratory trust study materials.

## Sueda Sen — evaluation design

The scored experiments are not run yet. This folder freezes the design so later annotation and retrieval work use the same rules.

| File | Purpose |
|---|---|
| `questions.seed.json` | Pilot questions, abstention cases, metric names, and success thresholds |
| `annotation_guidelines.json` | Entity/relation types, span rule, and the three clocks |

Primary success, from the proposal: temporal multi-hop accuracy above the strongest non-graph baseline, unsupported claims below 10%, and valid evidence for at least 90% of factual answer claims.

Do not mix a live collection run with a scored evaluation snapshot.
