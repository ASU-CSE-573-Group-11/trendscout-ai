# Interface

Conversational interface, citation display, evidence status, graph path, and latency logging.

Owner: Faisal Barkat Khorasi. Full write-up:
[`docs/faisal-trends-and-retrieval.md`](../docs/faisal-trends-and-retrieval.md).

## Input

A frozen `records.jsonl` snapshot plus a question. The agent builds the trend
signals, the hybrid retriever, and the graph from that snapshot; it never
collects anything live.

## Output

One answer bundle validated against
[`schemas/answer.schema.json`](../schemas/answer.schema.json), carrying the
answer text, claim-level citations, an evidence state and reason per claim, the
time window used and the snapshot date it was resolved against, the graph path
and the Cypher behind it, per-stage latency, and either an abstention with its
cause or a qualification naming the missing evidence.

```bash
python -m interface --demo --question "What happened with LangChain funding?"
python -m interface --demo --seed-questions --validate --out artifacts/answers.jsonl
streamlit run interface/app.py          # needs requirements-interface.txt
```

```python
from interface.agent import AgentConfig, TrendScoutAgent

agent = TrendScoutAgent(records, cohort=cohort, config=AgentConfig(mode="hybrid"))
answer = agent.answer(question, requires=["github", "jobs"])
```

## Modules

| File | Purpose |
|---|---|
| `agent.py` | Five timed stages: parse, route, retrieve, graph, generate |
| `evidence.py` | Evidence states per claim, conflict detection, staleness |
| `providers.py` | Extractive default and a pluggable LLM provider |
| `latency.py` | Per-stage timing and JSONL logging |
| `cli.py` | `python -m interface`, including every evaluation condition |
| `app.py` | Streamlit chat with citations, badges, and the graph path |

## Evaluation conditions

| Flag | Condition |
|---|---|
| `--mode hybrid\|bm25\|dense\|graph_only` | Retrieval comparison |
| `--no-graph` | Ablation: graph retrieval off |
| `--no-temporal-fields` | Ablation: time filtering and staleness off; the window is still reported |
| `--no-corroboration-weighting` | Ablation: ranking bonus off; evidence states unchanged |
| `--routing rules\|tfidf_logistic` | The two classical routers from the proposal |
| `--encoder`, `--min-origins`, `--stale-after-days`, `-k` | Parameter sweeps |
| `--latency-log PATH` | Per-stage timings, summarized by `scripts/latency_report.py` |

## Decision behaviour

Evidence states follow [`docs/evidence-ledger.md`](../docs/evidence-ledger.md)
and are assigned per claim. Copies sharing an `origin_cluster_id` count as one
origin. A dated past event does not become stale with time; operational
snapshots do. Conflicts are shown, not resolved.

The model sees only the selected, time-valid evidence. When evidence is
insufficient the system abstains and says why; when it is partial the answer is
qualified and names what is missing. Sentences a provider returns without a
citation are counted as unsupported rather than accepted.

## Test method

```bash
python -m pytest tests/test_interface_answers.py tests/test_retrieval_router.py
```

## Known limitations

- The default graph backend answers the competency queries in Python rather
  than executing Cypher; the selected query is reported but not run. The Neo4j
  backend is written against the driver API and has not been run against a live
  server.
- The Anthropic provider is written against the Messages API and has not been
  run with a key. Without one the agent falls back to extractive and says so.
- The default dense encoder is lexical, not semantic; results produced with it
  are a second lexical baseline. See the write-up.
- Latency figures come from a 95-record synthetic snapshot with no model call
  and no database.

## Sources and licenses

Team-authored. Optional dependencies in `requirements-interface.txt`:
Streamlit (Apache-2.0), sentence-transformers (Apache-2.0), FAISS (MIT), the
Neo4j driver (Apache-2.0), and the Anthropic SDK (MIT).
