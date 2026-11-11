# Weekly Features, Trend Baseline, and the Conversational Interface

Owner: Faisal Barkat Khorasi. Covers the Oct 28–Nov 5 and Nov 6–13 rows of
[`docs/project-plan.md`](project-plan.md): weekly GitHub activity features, the
EWMA baseline, dense retrieval, query routing, the conversational interface,
citation display, and latency logging.

## What this adds

| Module | Purpose |
|---|---|
| `signals/` | Weekly features from GitHub, job, and documentary records; EWMA plus rolling z-score; the LDA topic baseline; the trend-signal contract; graph export |
| `retrieval/dense.py`, `hybrid.py` | Dense passage index and reciprocal-rank fusion with Sueda's BM25 |
| `retrieval/router.py`, `timewindow.py` | Intent and time-window routing, with both classical baselines from the proposal |
| `retrieval/graph_queries.py`, `graph_access.py` | Mehmet's Cypher as named templates, a backend that answers them without a database, and Sector nodes from the frozen cohort |
| `interface/` | The agent, evidence states, citations, abstention, latency logging, a CLI, and a Streamlit chat UI |
| `schemas/trend_signal.schema.json`, `answer.schema.json` | The two contracts this module publishes |
| `evaluation/metrics.py`, `run_metrics.py` | Scoring for the answer bundles; scaffolding for the evaluation row |

Nothing in `collectors/`, `graph/`, or `retrieval/bm25.py` was modified.
`ontology/trendscout.ttl` gains three declarative lines (`ts:Sector`,
`ts:operatesIn`, `ts:sectorId`) for types the proposal already specifies.

## How to run it

```bash
python -m pip install -r requirements.txt
python -m pytest                       # 227 tests, no extra dependencies

# Weekly features and trend scoring over the fixture snapshot.
python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl \
    --question rising-with-hiring --weeks 8

# Write a trend bundle (trend_signals.jsonl, series.json, coverage.json).
python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl \
    --out artifacts/trends/fixture

# Ask a question, with citations, evidence states, and the graph path.
python -m interface --demo --question \
    "Which agent-infrastructure startups show both rising GitHub activity and new MLOps hiring during the last eight weeks?"

# Every retrieval condition and ablation the evaluation needs.
python -m interface --demo --seed-questions --mode bm25
python -m interface --demo --seed-questions --mode dense
python -m interface --demo --seed-questions --mode graph_only
python -m interface --demo --seed-questions --no-graph
python -m interface --demo --seed-questions --no-temporal-fields
python -m interface --demo --seed-questions --no-corroboration-weighting
python -m interface --demo --seed-questions --routing tfidf_logistic

# Latency.
python -m interface --demo --seed-questions --latency-log artifacts/latency.jsonl
python scripts/latency_report.py artifacts/latency.jsonl
```

Optional extras (`requirements-interface.txt`) add the Streamlit UI, a real
sentence-transformers encoder, FAISS, a live Neo4j driver, and an LLM provider.
None of them are required, and CI installs none of them.

```bash
python -m pip install -r requirements-interface.txt
streamlit run interface/app.py
```

## Milestone A: weekly features and the EWMA baseline

### The trend module is generic

`signals/series.py` models any weekly numeric series and `signals/ewma.py`
scores it. Neither knows about GitHub. Weekly commits, job counts by role
family, and distinct-origin news counts are three callers of the same code,
which is what the prototype questions need — they compare a development signal
against a hiring signal in one window.

### Design decisions

**Week assignment.** Vidya's GitHub collector emits one record per repository
per run, covering a trailing seven-day commit window, not a calendar week. A
window that exactly spans an ISO week is attributed to it (`aligned_window`).
Any other window is attributed to the ISO week containing its final instant and
flagged `window_end_approximate`, because the record does not expose per-commit
dates. If a later snapshot carries per-commit timestamps, each commit is placed
in its own week (`commit_timestamp`) and the flag disappears — the adapter
already reads that richer shape.

**Missing weeks.** A gap is either a real zero or "nobody looked", and guessing
wrong turns a collection gap into a fabricated decline. Each series declares
which it means:

| Family | Policy | Why |
|---|---|---|
| GitHub | `unknown` | A snapshot describes only the window it covers |
| Jobs | `unknown` | A board snapshot describes only the weeks a collector ran |
| News and company feeds | `zero` inside the coverage span | Feeds are harvested continuously, so a quiet week is a real observation of absence |

Weeks outside a series' coverage span are never materialised under either
policy.

**Deduplication.** Repeated collection must not inflate counts, so
deduplication happens twice: identical snapshots share a `content_hash` and
collapse to one observation, and overlapping windows are merged by the union of
their commit SHAs. In the fixture, an aligned window reporting 29 commits and an
overlapping window reporting 22 (20 of them the same commits) produce 31 for the
week, not 51.

**Running totals versus change.** Stars, forks, and open issues are current
counters. `star_delta` is the difference between **consecutive observed** weeks
only; when the previous ISO week was not observed the delta is `unknown`, because
a multi-week change presented as one week's growth is exactly the false alert
the evaluation measures.

**Repository quality.** Mirrors, forks, archived, and disabled repositories are
excluded by default with the reason recorded in the coverage report. Bot-heavy
repositories are flagged rather than dropped, and `human_commits` is reported
alongside `commits`. Where several snapshots contribute to one week, the bot
share comes from the most recent and the result is marked estimated.

**EWMA and the rolling z-score.** For each week with an observed value:

1. `baseline` is the EWMA level over weeks strictly before it, so it is a real
   one-step-ahead prediction;
2. `residual = value - baseline`;
3. `scale` is the dispersion of the trailing `window` residuals, as a sample
   standard deviation or a MAD-based robust estimate;
4. `z = residual / max(scale, min_scale)`, clipped at `z_cap`;
5. the level updates only then.

| Parameter | Default | Reason |
|---|---|---|
| `alpha` | 0.3 | Roughly a five-week effective memory, close to the eight-week windows in the questions |
| `window` | 8 | Matches the prototype question's "last eight weeks" |
| `threshold` | 1.5 | Reachable given the bound below, while leaving flat weeks flat |
| `min_history` | 4 | Fewer observed weeks cannot distinguish a trend from noise |
| `min_scale` | 1.0 | Count data is often constant for weeks; without a floor a one-commit change scores infinitely |
| `min_scale_points` | 3 | A dispersion estimate from two residuals is not one |
| `scale_method` | `std` | `mad` available for spiky series |
| `z_cap` | 10.0 | Bounds the reported score |

These are development-set starting points, not tuned results, and they are
reported with every signal.

**A bound worth knowing when tuning.** Because the current residual is part of
its own dispersion window, a single outlier week in a window of `n` residuals
scores exactly `sqrt(n)`, however large the spike. That bounds the false-alert
rate — one explosive week cannot dominate a ranking — and it means `threshold`
must stay below `sqrt(window)` to be reachable at all. The defaults leave
headroom: `1.5 < sqrt(8) = 2.83`. Sustained changes spread across several
residuals and are not subject to the bound. This is asserted in
`tests/test_trend_ewma.py`.

**Cold start and gaps.** A week is labelled `insufficient_history` rather than
`flat` whenever the evidence cannot support a direction: the first observed
week, fewer than `min_history` observed weeks, too few residuals for a
dispersion estimate, or an unknown value. Unknown weeks never update the level
and never enter the residual window, so a collection gap cannot produce a
`falling` label.

**Metrics the collector cannot supply.** Releases and issues opened/closed are
not collected; only a current `open_issues_count` exists, and it includes pull
requests. Active contributors cannot be derived at all, because commit author
names, emails, and profiles are discarded at collection time under the source
policy. These are reported as explicitly unavailable, with the reason, rather
than emitted as zeros. `--include-unavailable-metrics` emits them as all-unknown
series when a consumer wants the placeholder.

**Hiring features.** `open_postings` and `new_postings` per company, role
family, and explicitly mentioned skill. Role families come from explicit title
phrases, mirroring the explicit-mention rule the skill extraction already uses,
and a posting may join several families ("MLOps Engineer, Deployments" is both
`mlops` and `infrastructure`). `new_postings` is unknown in the first observed
week and across a collection gap. There is deliberately **no** `closed_postings`
metric: a posting leaving a board may have been filled, withdrawn, reposted, or
missed by a failed run.

**Attention features.** Distinct origin clusters per company per week. Counting
articles rather than origins would let one press release look like a wave of
coverage, and the evidence ledger is explicit that syndicated copies are not
independent corroboration.

**The LDA topic baseline.** Proposal section 3 lists LDA as the lightweight
trend-discovery baseline alongside distinct-source counts and EWMA.
`signals/topics.py` fits it by collapsed Gibbs sampling in plain Python, with
no scikit-learn or gensim, because CI installs only `requirements.txt`. The
sampler is seeded and its iteration order is fixed, so a frozen snapshot yields
the same topics every run — a baseline whose topics move between runs cannot be
compared against anything.

Topics are not a parallel pipeline: `topic_weekly_series` emits distinct-origin
counts per topic per ISO week, so "which topics are rising" is answered by the
same EWMA scorer as commits and hiring. Topic series are opt-in
(`--topics K`), so the other three families stay comparable between runs that
do and do not fit a model.

| Parameter | Default | Reason |
|---|---|---|
| `alpha` | 0.1 | The textbook 50/K is for long documents; on passages of a few dozen tokens it swamps the observed counts and leaves every document a near-uniform mixture |
| `beta` | 0.01 | Sparse topic-word prior, standard for short text |
| `iterations` / `burn_in` | 300 / 50 | Post-burn-in sweeps are averaged rather than taking one noisy final draw |
| `min_documents` | 25 | Below this the model is marked `underpowered` and the caveat is reported |

The alpha choice is not cosmetic: on a planted two-topic corpus the default
separates the vocabularies cleanly, and at 50/K it does not. Both behaviours
are asserted in `tests/test_topics_lda.py`.

### Traceability

Every trend signal carries the `record_id` values for the week it scores **and**
for the trailing residual window, so the ledger can audit the comparison
baseline rather than only the current value. Output is validated against
`schemas/trend_signal.schema.json`. `signals/graph_export.py` projects signals
into the same node and edge shape `graph/import_contract.py` produces, with
`DERIVED_FROM` edges to those records and `ABOUT` to the startup. No `Claim`
node is minted and no evidence state is assigned: a trend signal is one
operational signal, and `docs/evidence-ledger.md` reserves that decision for the
ledger. Edge statements `MATCH` their endpoints, so a signal never invents a
source record that was not loaded.

## Milestone B: retrieval, routing, answers

### Dense retrieval

The dense index uses the same unit BM25 does — one passage per record, title
plus text — so a BM25-versus-dense comparison is between two rankings of the
same documents.

Two encoders. `SentenceTransformerEncoder` (`all-MiniLM-L6-v2` by default) is
the real dense baseline and is optional, because CI installs only
`requirements.txt`. The default `HashingEncoder` is signed hashing over word
unigrams, word bigrams, and character trigrams, deterministic across processes
because it uses `hashlib` rather than the salted built-in `hash`.

> **Reporting caveat.** `HashingEncoder` is lexical, not semantic. A number
> produced with it is a **second lexical baseline**, not a dense-retrieval
> result. The encoder name and this caveat travel with the index, the saved
> file, and every answer bundle, so a reported metric always says which encoder
> produced it. Install `sentence-transformers` before running the scored dense
> condition.

### Hybrid fusion

Reciprocal rank fusion, `score(d) = Σ weight / (k + rank(d))` with `k = 60`.
BM25 scores and cosine similarities are on different unnormalized scales, so
summing them would weight one retriever by whatever range its scores happen to
occupy; RRF uses only ranks and needs no calibration and no labels. Per-retriever
rank and raw score are retained on every fused hit. Sueda's `bm25.py` is
constructed and queried as it is, never modified.

### Query router

| Intent | Strategies | Example |
|---|---|---|
| `exact` | graph | "Who invested in LangChain" |
| `aggregate` | graph, trend | "How many postings does CrewAI have" |
| `narrative` | documents | "Explain what LangSmith does" |
| `mixed_temporal` | graph, documents, trend | the first prototype question |
| `evidence_state` | graph, ledger | "Why is a company marked as emerging" |
| `unsupported` | none — abstain | "highest valuation in 2027" |

Both classical baselines from the proposal are implemented and selectable:
ordered intent rules (the default, because every decision names the rule that
fired) and a TF-IDF multinomial logistic classifier trained on 60 labelled
development questions, written in plain Python so it runs wherever the tests run.
The 60 questions are a development set, not an evaluation set; the classifier's
fit on them is a sanity check and not a result.

Two checks override both methods, because they are properties of the data rather
than guesses about intent: a question about a period **after** the snapshot
anchor, and one whose window closes **before** collection began. Together they
cover both insufficient-evidence seed questions, each for a stated reason.

### Time windows

Relative expressions resolve against the **snapshot anchor**, never
`datetime.now()`. "The last eight weeks" must mean the same eight weeks when the
frozen snapshot is scored again next month. The resolved bounds, the phrase that
produced them, and the anchor are reported with every answer, because readings
like "last quarter" are genuinely ambiguous and the answer should show which one
it used. A question with no temporal expression gets a window whose basis is
`none` — the full snapshot — which is reported rather than hidden.

### Graph access

`retrieval/graph_queries.py` reads `graph/*.cypher`, names each query from its
leading comment, and extracts its parameters; selection is by a distinctive
phrase rather than file position, so a reordered file cannot silently change
which query runs. All 11 queries load and all 11 expected purposes resolve.

`InMemoryGraph` answers those competency queries in Python over the payload
Mehmet's `records_to_graph` and my trend export produce, so the demo replays a
frozen snapshot with no database — which the proposal requires. It is an
equivalent, not the real thing: the selected Cypher travels with the answer but
is not executed, and every answer names the backend that produced it.
`Neo4jBackend` executes the real templates when a driver and server are
available; it is written against the official driver API and **has not been run
against a live instance**.

### Evidence states and abstention

States follow `docs/evidence-ledger.md` and are assigned **per claim**, so one
well-supported sentence cannot lend its standing to a neighbouring sentence that
nothing supports. Two rules that are easy to get wrong are implemented
explicitly:

- copies sharing an `origin_cluster_id` are **one** origin, so syndication can
  neither manufacture corroboration nor create a conflict with itself;
- a dated past event does **not** become stale because time passed; staleness
  applies to operational snapshots whose refresh windows lapsed.

Disputes are detected between distinct origins only: monetary amounts differing
by more than 10%, or dates more than 7 days apart. A conflict is shown, never
silently resolved.

Abstention has three distinct causes, each reported: the question falls outside
the snapshot's time coverage, retrieval found nothing in the window, or no
generated claim turned out supported. A question whose required evidence kinds
are only partly present is **qualified** and names what is missing, which is what
`answer_if_both_signals_else_qualify` asks for.

### Answer providers

`ExtractiveProvider` is the default: it assembles the answer from the selected
evidence and so cannot introduce an unsupported claim, and it needs no API key.
`AnthropicProvider` is handed only the selected, time-valid evidence and is
required to cite every sentence; sentences it returns uncited are counted and
reported as unsupported rather than quietly accepted, which is what makes the
proposal's unsupported-claim rate measurable. With no key the agent falls back to
extractive and records the reason in the answer bundle.

Findings — the statements that actually answer an aggregate or multi-signal
question — are computed from the trend signals and graph rows the answer already
cites and carry those citation numbers, so a finding is never an uncited
assertion. Sectors come from the frozen cohort's own `category` field, so the
third prototype question is answered by counting independent coverage origins
per sector against operational signals in the same window. Where a question
genuinely cannot be supported — no cohort supplied, so no `Sector` nodes — the
answer says so rather than grouping by company and calling it a sector answer.

### Evaluation hooks

Every condition is a CLI flag: `--mode {hybrid,bm25,dense,graph_only}`,
`--no-graph`, `--no-temporal-fields`, `--no-corroboration-weighting`,
`--routing {rules,tfidf_logistic}`, `--encoder`, `--min-origins`,
`--stale-after-days`, `--k`. `--out` writes answer bundles as JSONL and
`--validate` checks every bundle against `schemas/answer.schema.json`.

Each bundle carries what the metrics need: `question_id` to join to labels and
expected behaviours, `citations` with `record_ids` and `origin_cluster_ids` for
Precision@5 / Recall@5 / MRR / nDCG@5, `claims` with `supported` and
`evidence_state` for claim-support rate and citation precision, `abstained`
with `abstention_reason` for abstention accuracy, and `latency` per stage.

`evaluation/run_metrics.py` computes all of that and compares conditions side
by side:

```bash
for mode in hybrid bm25 dense graph_only; do
  python -m interface --demo --seed-questions --mode $mode --out artifacts/answers-$mode.jsonl
done
python evaluation/run_metrics.py artifacts/answers-*.jsonl --qrels <labels>
```

Abstention accuracy, claim-support rate, unsupported-claim rate, and latency
need no labels and are checked against the success thresholds already recorded
in `questions.seed.json`. The ranking metrics need judgements; without them
they print `n/a` rather than `0`, and unjudged questions are excluded with the
count stated rather than scored as misses. `qrels.example.json` documents the
format and is flagged `illustrative`, because its grades came from one run's
own citations; the runner prints a banner when that flag is set.

The corroboration-weighting ablation changes **ranking only**. Evidence states
follow the ledger's rules regardless of how a passage was ranked, which isolates
the ranking effect from the state assignment.

## First numbers

All numbers below come from the committed fixture snapshot
(`tests/fixtures/faisal/snapshot_records.jsonl`, 95 synthetic records in Vidya's
record layout). They are a pipeline check, **not** results: the data is
synthetic and there are no relevance labels yet.

### Snapshot and features

| | |
|---|---|
| Records | 95 (37 github, 53 job, 3 news, 1 company, 1 public_voice) |
| Series built | 93 (36 github, 48 jobs, 9 news) |
| Trend signals | 801 — 55 rising, 353 flat, 393 insufficient_history (841 with `--topics 3`) |
| Snapshot week / last data week | 2026-W45 / 2026-W44 |
| GitHub observations | 37 received, 28 used (1 exact replay deduplicated, 8 from the excluded mirror) |
| Excluded repositories | `run-llama/llama_index-mirror` (mirror) |
| Flagged | `crewAIInc/crewAI` bot-heavy; `langchain-ai/langchain@2026-W44` approximate week assignment |

The large `insufficient_history` share is expected and correct: most job and
skill series are short, and the fixture deliberately contains an unobserved week.

### A sample scored series

`github:commits|company=langchain`, defaults (`alpha=0.3`, `window=8`,
`threshold=1.5`):

| Week | Value | Baseline | z | Label |
|---|---|---|---|---|
| 2026-W36 | 12 | — | — | insufficient_history (cold start) |
| 2026-W37 | 11 | 12.00 | — | insufficient_history (2 observed weeks) |
| 2026-W38 | 13 | 11.70 | — | insufficient_history (3 observed weeks) |
| 2026-W39 | 12 | 12.09 | −0.08 | flat |
| 2026-W40 | 14 | 12.06 | 1.46 | flat |
| 2026-W41 | 16 | 12.64 | 1.97 | rising |
| 2026-W42 | — | 13.65 | — | insufficient_history (unknown week) |
| 2026-W43 | 37 | 13.65 | 2.54 | rising |
| 2026-W44 | 40 | 20.66 | 1.93 | rising |

Note W42: the level is carried across the gap unchanged, and W43 is scored
against the pre-gap baseline rather than against a fabricated zero.

### The first prototype question

"Which agent-infrastructure startups show both rising GitHub activity and new
MLOps hiring during the last eight weeks?" over 2026-W37–W44:

| Company | Rising activity weeks (score) | New MLOps postings | Supporting records |
|---|---|---|---|
| langchain | W41 (1.97), W43 (2.54), W44 (1.93) | W43, W44 | 9 |
| crewai | W43 (2.49), W44 (1.94) | W44 | 3 |

`llamaindex` is correctly absent: its commits are flat and it posted no MLOps
role.

### Retrieval sanity check

Top-3 titles, same snapshot, `k=3`:

| Query | BM25 | Dense (hashing) | Hybrid |
|---|---|---|---|
| "LangSmith evaluation datasets" | LangSmith datasets post, Evaluation Engineer, Series B article | LangSmith datasets post, Evaluation Engineer, langchain repo | LangSmith datasets post, Evaluation Engineer, langchain repo |
| "MLOps engineer kubernetes" | MLOps Engineer, MLOps Deployments, Platform Engineer | identical | identical |
| "Series B funding round" | Series B article only | Series B article, LlamaIndex post, ML Operations Lead | Series B article, LlamaIndex post, ML Operations Lead |

The three columns agree closely, which is the expected result and not a finding:
with the fallback encoder both retrievers are lexical. The comparison becomes
meaningful once `sentence-transformers` is installed. The third row does show
the one real difference available here — BM25 returns a single hit where the
dense index returns three, so fusion improves recall.

### Latency

24 requests (the 6 seed questions × 4 retrieval modes), extractive provider,
in-memory graph:

| Stage | Median (ms) | p90 (ms) |
|---|---|---|
| parse | 0.04 | 0.05 |
| route | 0.19 | 0.25 |
| retrieve | 0.13 | 0.59 |
| graph | 0.74 | 3.80 |
| generate | 1.26 | 1.67 |
| **total** | **2.67** | **6.27** |

Against the proposal's 8-second median target: met with four orders of
magnitude of headroom — but on 95 records, with no model call and no database.
The figures that will matter are an LLM provider (seconds), a real embedding
model, and a live Neo4j. The stage breakdown exists so those are attributable
when they arrive.

### Evidence behaviour on the seed set

All 6 seed questions produce schema-valid bundles. 2 abstain (both
insufficient-evidence cases, each for a stated reason), 4 are qualified, and
**0 of 18 claims are unsupported** — expected with the extractive provider,
which cannot assert anything the evidence does not contain. That number is the
one to watch when an LLM provider is enabled.

### Dense retrieval with the real encoder

Repeated with `sentence-transformers/all-MiniLM-L6-v2` installed. The index then
reports `semantic: true` and drops the caveat automatically. Top-3 titles:

| Query | BM25 | Dense (MiniLM) |
|---|---|---|
| "LangSmith evaluation datasets" | LangSmith post, Evaluation Engineer, Series B article | LangSmith post, Evaluation Engineer, llama_index repo |
| "MLOps engineer kubernetes" | MLOps Engineer, MLOps Deployments, Platform Engineer | MLOps Engineer, MLOps Deployments, ML Operations Lead |
| **"who is hiring for search relevance work"** | **langgraph repo, LlamaIndex post, llama_index repo** | **Retrieval Engineer, Software Engineer (Retrieval)** |
| "framework for building agents" | llama_index repo, LlamaIndex post, CrewAI interview | langchain repo, CrewAI interview, langgraph repo |

The third row is the one that matters: the query shares no content word with
the postings it should find, so BM25 cannot reach them and the dense index
does. That is the comparison the evaluation is for, and it only appears with a
real model — which is why a number produced with the hashing fallback must not
be reported as dense retrieval.

Dense query latency is ~5 ms after a one-off ~11 s model load.

## Known limitations

1. **The fixtures are synthetic.** Every number above is a pipeline check. Real
   numbers need a live collection run. Compatibility with the collector's own
   output is verified (see below), so only the data is missing, not the wiring.
2. **The Neo4j backend is unverified.** Written against the driver API, never
   run against a server. The in-memory equivalent is the default and the demo
   does not need a database.
3. **The LLM provider path is unverified.** Written against the Messages API,
   never run with a key. The extractive provider is the default.
4. **No relevance labels exist**, so no retrieval metric is reported here. The
   hooks are in place for the scored runs.
5. **Week assignment is approximate** for any collection window that does not
   align to an ISO week. Flagged per week; resolved if per-commit dates are
   added upstream.
6. **Bot-share estimation** is approximate when several snapshots contribute to
   one week, and is marked as estimated.
7. **Sector coverage follows the snapshot.** Only cohort companies the snapshot
   holds records for are sector-tagged, so a sector answer describes the
   companies with evidence, not the whole cohort.

## Integration status

Verified rather than assumed:

- **The collector's own output works unchanged.** Vidya's collectors were run
  from her branch against their own fixtures, and the resulting records fed
  through `signals/adapters.py` and the full pipeline: GitHub records
  deduplicated correctly, job records read with her skill vocabulary, the
  rolling seven-day window flagged as not ISO-aligned, bot and human commits
  split correctly. Two integration tests in
  `tests/test_integration_collectors.py` cover this and skip until the
  collectors land on the branch.
- **The branches merge cleanly.** This branch merged with
  `vidya/api-collectors` produces no conflicts, and the combined suite is
  **258 passed, 0 skipped** — her 49 collector tests, my tests, and the two
  integration tests that activate on merge.
- **Mehmet's graph tests are unaffected** by the three declarative lines added
  to the ontology: 11 graph, RDF, SHACL, and evidence tests pass.

## Open dependencies on teammates

Short, because most of the earlier list turned out to be work that could be
finished here instead.

| Needed from | What | Why it is not blocking |
|---|---|---|
| Vidya | A real cohort collection run | Only data is missing; the wiring is verified against her code |
| Mehmet | A live Neo4j load | `Neo4jBackend` is written; the in-memory equivalent serves the demo |
| Mehmet | `Claim` nodes from the evidence ledger | Multi-hop paths reach trend signals today; claim paths appear automatically once claims load |
| Sueda | Relevance labels against the frozen snapshot | Needed to report retrieval metrics; every condition, ablation, and the scoring runner already work |
| Team | Whether to enable the Anthropic provider, and whose key | The extractive fallback runs without one |

Nice-to-have, not needed: per-commit `committed_at` in
`metadata.activity_window` would remove approximate week assignment entirely,
and release counts plus issues opened/closed as events would cover three of the
four metrics currently reported as unavailable.

## Conflicts found between the proposal, the plan, and the code

1. The proposal's §6 and §7 list a fifth member, **Baaz Jhaj**, owning "GitHub
   collector; weekly activity features; EWMA baseline; repository-quality
   controls". `docs/project-plan.md` has four members and reassigns the
   collector to Vidya and the weekly features and EWMA to me. I followed the
   plan, as it is the live work division. That member has since left the team;
   his row is fully covered — the collector by PR #3, and the features, EWMA,
   and repository-quality controls here.
2. Consequently the proposal gives me only the Nov 6–13 row; the plan adds the
   Oct 28–Nov 5 EWMA work. That work was already overdue, not due Nov 13.
3. Proposal §3 listed an **LDA topic baseline** under trend discovery that
   `project-plan.md` assigned to nobody. Since trend discovery is now my
   module, it is implemented here (`signals/topics.py`) rather than left
   unowned.
4. `.github/workflows/sueda-collectors.yml` installs only `requirements.txt` on
   Python 3.11, so FAISS, sentence-transformers, Streamlit, Neo4j, and the
   Anthropic SDK cannot be test dependencies. Every one of them is optional with
   a working fallback, and the full suite passes without them.
