"""Streamlit chat interface with a citations panel, evidence badges, and the graph path.

Run it from the repository root::

    python -m pip install -r requirements-interface.txt
    streamlit run interface/app.py

The repository had no UI, so this is a new one. It is a thin view over
:class:`interface.agent.TrendScoutAgent`: everything shown here comes from the
answer bundle, so what the user sees and what the evaluation scores are the same
object. The sidebar exposes the retrieval conditions and ablation switches, which
makes the demo and the evaluation conditions the same code path.

Streamlit is an optional dependency and is not installed in CI, so importing
this module without it raises a clear error rather than an ImportError
traceback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Streamlit is not installed. Install requirements-interface.txt, or use the CLI: "
        "python -m interface --demo --question '...'"
    ) from exc

from interface.agent import AgentConfig, Answer, TrendScoutAgent
from interface.evidence import EvidenceConfig
from retrieval.handoff import load_records_jsonl

ROOT = Path(__file__).resolve().parents[1]
DEMO_SNAPSHOT = ROOT / "tests" / "fixtures" / "faisal" / "snapshot_records.jsonl"
COHORT = ROOT / "data" / "registry" / "cohort.json"
SEED_QUESTIONS = ROOT / "evaluation" / "questions.seed.json"

STATE_STYLE: dict[str, tuple[str, str]] = {
    "corroborated": ("🟢", "two or more independent origins, or a document plus an operational signal"),
    "emerging": ("🟡", "one independent origin, nothing contradicting it"),
    "disputed": ("🔴", "independent origins disagree on a material value"),
    "stale": ("🟠", "the supporting snapshots are past their refresh windows"),
    "insufficient": ("⚪", "the evidence does not justify a factual answer"),
}


@st.cache_resource(show_spinner="Loading the frozen snapshot…")
def load_agent(
    snapshot: str,
    mode: str,
    routing: str,
    provider: str,
    use_graph: bool,
    use_temporal_fields: bool,
    use_corroboration_weighting: bool,
    minimum_origins: int,
    k: int,
) -> TrendScoutAgent:
    path = Path(snapshot)
    records = load_records_jsonl(path)
    cohort = json.loads(COHORT.read_text(encoding="utf-8")) if COHORT.exists() else {}
    return TrendScoutAgent(
        records,
        config=AgentConfig(
            mode=mode,
            k=k,
            routing_method=routing,
            provider=provider,
            use_graph=use_graph,
            use_temporal_fields=use_temporal_fields,
            use_corroboration_weighting=use_corroboration_weighting,
            demo_mode=path == DEMO_SNAPSHOT,
        ),
        evidence_config=EvidenceConfig(minimum_independent_origins=minimum_origins),
        cohort=cohort,
        latency_log=ROOT / "artifacts" / "latency.jsonl",
        snapshot_id=f"{path.name}@{len(records)}records",
    )


def badge(state: str) -> str:
    icon, _ = STATE_STYLE.get(state, ("⚪", ""))
    return f"{icon} {state}"


def render_answer(answer: Answer) -> None:
    if answer.abstained:
        st.warning(f"**Abstained.** {answer.abstention_reason}")
    st.markdown(answer.answer_text)

    if answer.qualification:
        st.info(answer.qualification)
    if answer.missing_evidence and not answer.abstained:
        st.caption("Missing evidence: " + ", ".join(answer.missing_evidence))

    window = answer.time_window
    columns = st.columns(4)
    columns[0].metric("Evidence state", badge(answer.overall_state))
    columns[1].metric("Citations", len(answer.citations))
    columns[2].metric("Unsupported claims", answer.unsupported_claim_count)
    columns[3].metric("Total latency", f"{answer.latency.get('total', 0):.0f} ms")

    st.caption(
        f"Time window: **{window.label}** "
        + (f"({window.start} → {window.end})" if window.start else f"(up to {window.end})")
        + f" · resolved against the snapshot date {window.anchor}, not today"
        + f" · intent **{answer.route.intent}** via {answer.route.method}"
    )

    if answer.claims:
        with st.expander(f"Claims and evidence states ({len(answer.claims)})", expanded=True):
            for index, claim in enumerate(answer.claims, start=1):
                markers = " ".join(f"`[{number}]`" for number in claim.citation_numbers) or "`uncited`"
                icon, meaning = STATE_STYLE.get(claim.assessment.state, ("⚪", ""))
                st.markdown(
                    f"{icon} **{claim.assessment.state}** {markers} — {claim.text}"
                    + ("" if claim.supported else "  \n:red[unsupported]")
                )
                st.caption(f"{claim.assessment.reason} ({meaning})")
                for conflict in claim.assessment.conflicts:
                    st.error(f"Conflict ({conflict.kind}): {conflict.detail}")

    if answer.citations:
        with st.expander(f"Citations ({len(answer.citations)})", expanded=True):
            for citation in answer.citations:
                header = f"**[{citation.number}]** `{citation.kind}`"
                if citation.source_type:
                    header += f" · `{citation.source_type}`"
                if citation.company_id:
                    header += f" · {citation.company_id}"
                if citation.when:
                    header += f" · {citation.when} ({citation.time_basis})"
                st.markdown(header)
                if citation.title:
                    st.markdown(f"*{citation.title}*")
                if citation.source_url:
                    st.markdown(citation.source_url)
                if citation.text:
                    st.caption(citation.text[:600])
                detail = {key: value for key, value in citation.detail.items() if value is not None}
                if detail:
                    st.caption(json.dumps(detail, sort_keys=True, default=str))
                st.divider()

    if answer.graph_paths:
        with st.expander(f"Graph path ({len(answer.graph_paths)})", expanded=True):
            st.caption(
                "Evidence paths as stored. A record points at both its startup and its attached "
                "claim or trend signal, so a path may have two segments separated by `;`."
            )
            for path in answer.graph_paths[:8]:
                st.code(path.render(), language="text")
            for result in answer.graph_results:
                if result.template:
                    st.caption(f"{result.purpose} — `{result.template.name}` ({result.backend})")
                    st.code(result.template.query, language="cypher")
                    break

    if answer.trend_signals:
        with st.expander(f"Trend signals ({len(answer.trend_signals)})"):
            st.caption(
                "A trend signal describes observed weekly activity against its own recent "
                "baseline. It is not a prediction."
            )
            st.dataframe(
                [
                    {
                        "company": signal.company_id,
                        "metric": signal.metric,
                        "week": signal.iso_week,
                        "value": signal.value,
                        "baseline": None if signal.ewma_baseline is None else round(signal.ewma_baseline, 2),
                        "score": None if signal.trend_score is None else round(signal.trend_score, 2),
                        "label": signal.label,
                        "records": len(signal.record_ids),
                    }
                    for signal in answer.trend_signals
                ],
                hide_index=True,
            )

    with st.expander("Latency by stage"):
        st.dataframe(
            [{"stage": stage, "ms": round(value, 2)} for stage, value in sorted(answer.latency.items())],
            hide_index=True,
        )
        provider = answer.provider
        line = f"Provider: `{provider.provider}`"
        if provider.model:
            line += f" / `{provider.model}`"
        if provider.fallback_used:
            line += f" — fell back to extractive: {provider.fallback_reason}"
        st.caption(line)


def main() -> None:
    st.set_page_config(page_title="TrendScout AI", page_icon="📈", layout="wide")
    st.title("TrendScout AI")
    st.caption(
        "Temporal knowledge graph and evidence-aware retrieval over a frozen snapshot of "
        "AI-startup signals. Answers carry claim-level citations, an evidence state per claim, "
        "the time window used, and the graph path — or an explicit abstention."
    )

    with st.sidebar:
        st.header("Snapshot")
        snapshot = st.text_input("records.jsonl", value=str(DEMO_SNAPSHOT))
        st.caption("Demo mode replays the committed fixture snapshot, so the demo works offline.")

        st.header("Retrieval condition")
        mode = st.selectbox("Mode", ("hybrid", "bm25", "dense", "graph_only"))
        k = st.slider("Passages (k)", 1, 20, 5)
        routing = st.selectbox("Router", ("rules", "tfidf_logistic"))
        provider = st.selectbox("Answer provider", ("extractive", "anthropic"))
        st.caption("The Anthropic provider falls back to extractive with no API key, and says so.")

        st.header("Ablations")
        use_graph = not st.checkbox("Disable graph retrieval")
        use_temporal_fields = not st.checkbox("Disable temporal fields")
        use_corroboration_weighting = not st.checkbox("Disable corroboration weighting")

        st.header("Evidence thresholds")
        minimum_origins = st.slider("Independent origins for corroborated", 1, 4, 2)

    agent = load_agent(
        snapshot,
        mode,
        routing,
        provider,
        use_graph,
        use_temporal_fields,
        use_corroboration_weighting,
        minimum_origins,
        k,
    )

    with st.sidebar:
        st.header("Loaded")
        description = agent.describe()
        st.caption(
            f"{description['records']} records · snapshot {description['snapshot_anchor']} · "
            f"last data week {description['trend']['last_data_week']}"
        )
        st.caption(f"graph backend: `{description['graph']['backend']}`")
        dense = description["retrieval"]["dense"]
        st.caption(f"dense encoder: `{dense['encoder']}` (semantic: {dense['semantic']})")
        if dense.get("caveat"):
            st.warning(dense["caveat"])

    seed = json.loads(SEED_QUESTIONS.read_text(encoding="utf-8"))["questions"]
    st.subheader("Try a seed question")
    chosen = st.selectbox(
        "From evaluation/questions.seed.json",
        ["—"] + [item["question"] for item in seed],
    )
    needs_by_question = {item["question"]: item.get("needs", []) for item in seed}

    if "history" not in st.session_state:
        st.session_state.history = []

    for entry in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(entry["question"])
        with st.chat_message("assistant"):
            render_answer(entry["answer"])

    question: str | None = st.chat_input("Ask about the cohort…")
    if chosen != "—" and st.button("Ask the selected seed question"):
        question = chosen

    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Retrieving, querying the graph, and assembling citations…"):
                answer = agent.answer(question, requires=needs_by_question.get(question, []))
            render_answer(answer)
        st.session_state.history.append({"question": question, "answer": answer})


if __name__ == "__main__":
    main()
