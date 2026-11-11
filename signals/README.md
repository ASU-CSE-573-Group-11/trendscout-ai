# Signals

Weekly activity features and the EWMA trend baseline.

Owner: Faisal Barkat Khorasi. Full write-up:
[`docs/faisal-trends-and-retrieval.md`](../docs/faisal-trends-and-retrieval.md).

## Input

Normalized source records validated against
[`schemas/record.schema.json`](../schemas/record.schema.json): GitHub snapshots
and job postings from Vidya's collectors, and news, company, and public-voice
records from Sueda's pipeline. `signals/adapters.py` is the only module that
reads their `metadata` layout.

## Output

Trend signals validated against
[`schemas/trend_signal.schema.json`](../schemas/trend_signal.schema.json), one
per series per ISO week, each carrying the `record_id` values for the scored
week and for the trailing residual window.

```python
from pathlib import Path
from retrieval.handoff import load_records_jsonl
from signals.pipeline import run_trend_pipeline, rising_with_new_hiring, write_trend_bundle

records = load_records_jsonl(Path("tests/fixtures/faisal/snapshot_records.jsonl"))
run = run_trend_pipeline(records)
matches = rising_with_new_hiring(run, window_weeks=8)
write_trend_bundle(run, Path("artifacts/trends/fixture"))
```

```bash
python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl \
    --question rising-with-hiring --weeks 8
python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl --cypher
```

A bundle contains `trend_signals.jsonl`, `series.json`, and `coverage.json`,
matching the layout of Sueda's collection bundle.

## Modules

| File | Purpose |
|---|---|
| `weeks.py` | ISO week arithmetic in UTC |
| `series.py` | `WeeklySeries` with explicit missing-week semantics |
| `ewma.py` | EWMA baseline, rolling z-score, and the four labels |
| `contract.py` | Validation and JSONL I/O for the trend contract |
| `adapters.py` | The one place that reads the collectors' metadata layout |
| `github_features.py` | Weekly commits, human commits, star and issue deltas |
| `job_features.py` | Open and new postings per company, role family, and skill |
| `news_features.py` | Distinct-origin attention counts |
| `pipeline.py` | Build and score everything from one snapshot |
| `graph_export.py` | Nodes, edges, and Cypher for the evidence ledger |
| `cli.py` | `python -m signals` |

## Method

The scorer is generic over any weekly series; GitHub, hiring, and attention are
three callers. Per scored week: the EWMA baseline is computed from weeks
strictly before it, the residual is divided by the dispersion of the trailing
residual window subject to a floor, and the result is labelled `rising`,
`flat`, `falling`, or `insufficient_history`.

Defaults: `alpha=0.3`, `window=8`, `threshold=1.5`, `min_history=4`,
`min_scale=1.0`, `scale_method=std`. They are development-set starting points
and are reported with every signal.

A missing week is never guessed. GitHub and job series treat an unobserved week
as `unknown`; news series treat a quiet week inside the coverage span as a real
zero. Unknown weeks do not update the level and do not enter the residual
window, so a collection gap cannot produce a `falling` label.

## Test method

```bash
python -m pytest tests/test_weekly_features.py tests/test_trend_ewma.py \
    tests/test_trend_graph_export.py
```

Fixtures reproduce Vidya's record layout and are regenerated with
`python scripts/build_faisal_fixtures.py`. They deliberately contain a missing
week, a non-ISO-aligned window, two overlapping windows in one week, an exact
replay, a mirror repository, a bot-heavy repository, a short-history
repository, and two syndicated articles sharing one origin.

## Known limitations

- Weekly attribution is approximate for any collection window that does not
  align to an ISO week; those weeks are flagged, and per-commit timestamps
  upstream would remove the approximation.
- Releases, issues opened/closed, and active contributors are not collected and
  are reported as unavailable rather than as zeros. Active contributors cannot
  be derived at all: author identities are discarded at collection time.
- Bot-share estimation is approximate when several snapshots contribute to one
  week, and is marked as estimated.
- A trend signal is never a claim about future performance, and this module
  assigns no evidence state; that is the ledger's decision.

## Sources and licenses

Team-authored. Depends only on `jsonschema` (MIT) through the shared record
contract. Fixtures are synthetic.
