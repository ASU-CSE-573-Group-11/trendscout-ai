"""The conversational agent: parse, route, retrieve, query the graph, answer.

One request runs five timed stages and produces an :class:`Answer` carrying the
citations, the evidence state of every claim, the time window that was used, and
the graph path. The answer is validated against ``schemas/answer.schema.json``.

Three properties the rest of the system depends on:

**The model only ever sees selected, time-valid evidence.** The evidence bundle
is assembled after routing and time filtering, and the provider is handed that
bundle and nothing else -- never the snapshot, never a record outside the window.

**Insufficient evidence produces an abstention, not a guess.** Abstention happens
for three distinct reasons, each reported: the question is outside the snapshot's
time coverage, retrieval found nothing in the window, or every claim the provider
produced turned out unsupported. A question whose required evidence kinds are
only partly present is qualified rather than abstained, as the seed questions ask.

**Ablations are configuration.** Retrieval mode, graph retrieval, temporal
fields, and corroboration weighting are switches on :class:`AgentConfig`, so the
evaluation conditions run from a CLI flag rather than an edited file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from interface.evidence import (
    EvidenceAssessment,
    EvidenceConfig,
    assess_evidence,
    worst_state,
)
from interface.latency import LatencyLog, StageTimings
from interface.providers import (
    AnswerProvider,
    ExtractiveProvider,
    ProviderResult,
    build_provider,
    split_claims,
)
from retrieval.graph_access import GraphPath, GraphResult, InMemoryGraph
from retrieval.hybrid import HybridRetriever, RetrievalConfig
from retrieval.passages import Passage
from retrieval.router import QueryRouter, RouteDecision
from retrieval.timewindow import TimeWindow, parse_time_window
from signals.contract import to_payload
from signals.ewma import TrendSignal
from signals.pipeline import TrendRun, run_trend_pipeline
from signals.weeks import parse_instant

ANSWER_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "answer.schema.json"

RETRIEVAL_MODES: tuple[str, ...] = ("hybrid", "bm25", "dense", "graph_only")


@dataclass(frozen=True)
class AgentConfig:
    """Everything the evaluation needs to vary, in one place."""

    mode: str = "hybrid"
    k: int = 5
    routing_method: str = "rules"
    provider: str | None = None
    encoder: str | None = None
    distinct_origins: bool = True
    # Ablation switches, named as the proposal names them.
    use_graph: bool = True
    use_temporal_fields: bool = True
    use_corroboration_weighting: bool = True
    corroboration_bonus: float = 0.25
    demo_mode: bool = False
    target_median_ms: float = 8000.0
    # Citation budgets. Passages are limited by k; these cap the derived
    # evidence so a citations panel stays readable and the model is not handed
    # hundreds of items it cannot use.
    max_trend_citations: int = 8
    max_graph_citations: int = 3
    max_companies_queried: int = 6

    def __post_init__(self) -> None:
        if self.mode not in RETRIEVAL_MODES:
            raise ValueError(f"unsupported mode: {self.mode}; choose from {RETRIEVAL_MODES}")
        if self.k < 1:
            raise ValueError("k must be at least 1")

    @property
    def retrieval_config(self) -> RetrievalConfig:
        mode = "hybrid" if self.mode == "graph_only" else self.mode
        return RetrievalConfig(mode=mode, distinct_origins=self.distinct_origins)

    @property
    def documents_enabled(self) -> bool:
        return self.mode != "graph_only"

    @property
    def graph_enabled(self) -> bool:
        return self.use_graph

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["documents_enabled"] = self.documents_enabled
        payload["ablations"] = {
            "graph_retrieval": self.use_graph,
            "temporal_fields": self.use_temporal_fields,
            "corroboration_weighting": self.use_corroboration_weighting,
        }
        return payload


@dataclass
class Citation:
    """One numbered evidence item, as shown in the citations panel."""

    number: int
    kind: str
    record_ids: tuple[str, ...]
    origin_cluster_ids: tuple[str, ...]
    source_type: str | None
    title: str | None
    source_url: str | None
    publisher: str | None
    company_id: str | None
    when: str | None
    time_basis: str | None
    text: str | None
    retrievers: Mapping[str, Any] = field(default_factory=dict)
    score: float | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "kind": self.kind,
            "record_ids": list(self.record_ids),
            "origin_cluster_ids": list(self.origin_cluster_ids),
            "source_type": self.source_type,
            "title": self.title,
            "source_url": self.source_url,
            "publisher": self.publisher,
            "company_id": self.company_id,
            "when": self.when,
            "time_basis": self.time_basis,
            "text": self.text,
            "retrievers": dict(self.retrievers),
            "score": self.score,
            "detail": dict(self.detail),
        }


@dataclass
class Claim:
    """One sentence of the answer, with its citations and evidence state."""

    text: str
    citation_numbers: tuple[int, ...]
    assessment: EvidenceAssessment

    @property
    def supported(self) -> bool:
        return bool(self.citation_numbers) and self.assessment.supported

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "citation_numbers": list(self.citation_numbers),
            "evidence_state": self.assessment.state,
            "evidence_reason": self.assessment.reason,
            "supported": self.supported,
            "independent_origin_count": self.assessment.independent_origin_count,
            "record_ids": list(self.assessment.record_ids),
            "conflicts": [conflict.as_dict() for conflict in self.assessment.conflicts],
        }


@dataclass
class Answer:
    """The full answer bundle returned to the interface and the evaluation."""

    question: str
    question_id: str | None
    answer_text: str
    claims: list[Claim]
    citations: list[Citation]
    route: RouteDecision
    time_window: TimeWindow
    graph_results: list[GraphResult]
    graph_paths: list[GraphPath]
    trend_signals: list[TrendSignal]
    overall_state: str
    abstained: bool
    abstention_reason: str | None
    missing_evidence: list[str]
    qualified: bool
    qualification: str | None
    provider: ProviderResult
    latency: Mapping[str, float]
    config: Mapping[str, Any]
    snapshot: Mapping[str, Any]

    @property
    def unsupported_claim_count(self) -> int:
        return sum(1 for claim in self.claims if not claim.supported)

    @property
    def unsupported_claim_rate(self) -> float:
        return self.unsupported_claim_count / len(self.claims) if self.claims else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "question_id": self.question_id,
            "answer_text": self.answer_text,
            "claims": [claim.as_dict() for claim in self.claims],
            "citations": [citation.as_dict() for citation in self.citations],
            "route": self.route.as_dict(),
            "time_window": self.time_window.as_dict(),
            "graph": [result.as_dict() for result in self.graph_results],
            "graph_paths": [path.as_dict() for path in self.graph_paths],
            "trend_signals": to_payload(self.trend_signals),
            "overall_state": self.overall_state,
            "abstained": self.abstained,
            "abstention_reason": self.abstention_reason,
            "missing_evidence": list(self.missing_evidence),
            "qualified": self.qualified,
            "qualification": self.qualification,
            "unsupported_claim_count": self.unsupported_claim_count,
            "unsupported_claim_rate": round(self.unsupported_claim_rate, 4),
            "provider": self.provider.as_dict(),
            "latency": dict(self.latency),
            "config": dict(self.config),
            "snapshot": dict(self.snapshot),
        }


def validate_answer(payload: Mapping[str, Any]) -> list[str]:
    """Schema errors for an answer bundle, empty when valid."""
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(ANSWER_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [error.message for error in validator.iter_errors(payload)]


class TrendScoutAgent:
    """Answer questions over one frozen snapshot."""

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        config: AgentConfig | None = None,
        evidence_config: EvidenceConfig | None = None,
        cohort: Mapping[str, Any] | None = None,
        trend_run: TrendRun | None = None,
        retriever: HybridRetriever | None = None,
        graph: InMemoryGraph | None = None,
        provider: AnswerProvider | None = None,
        latency_log: Path | None = None,
        snapshot_id: str | None = None,
    ) -> None:
        self.records = list(records)
        self.config = config or AgentConfig()
        self.evidence_config = evidence_config or EvidenceConfig()
        self.cohort = cohort or {}

        self.trend_run = trend_run or run_trend_pipeline(self.records)
        self.snapshot_anchor = _snapshot_anchor(self.records)

        company_ids = [
            company["company_id"] for company in self.cohort.get("companies", []) if company.get("company_id")
        ] or sorted({record["company_id"] for record in self.records if record.get("company_id")})
        aliases = {
            company["company_id"]: company.get("aliases", [])
            for company in self.cohort.get("companies", [])
            if company.get("company_id")
        }
        study_window = self.cohort.get("study_window") or {}
        coverage_start = f"{study_window['start']}T00:00:00Z" if study_window.get("start") else None

        self.router = QueryRouter(
            snapshot_anchor=self.snapshot_anchor,
            method=self.config.routing_method,
            company_ids=company_ids,
            aliases=aliases,
            coverage_start=coverage_start,
        )
        self.retriever = retriever or HybridRetriever.from_records(
            self.records,
            config=self.config.retrieval_config,
            encoder=_encoder(self.config.encoder),
        )
        self.graph = graph or InMemoryGraph.from_records(
            self.records,
            trend_signals=to_payload(self.trend_run.signals),
            cohort=self.cohort,
        )
        requested = provider or build_provider(self.config.provider)
        usable, reason = requested.available()
        self.provider: AnswerProvider = requested if usable else ExtractiveProvider()
        self.provider_fallback_reason = None if usable else reason
        self.latency = LatencyLog(path=latency_log) if latency_log else None
        self.snapshot_id = snapshot_id or f"records:{len(self.records)}@{self.snapshot_anchor}"

    # -- orchestration ---------------------------------------------------

    def answer(
        self,
        question: str,
        *,
        requires: Sequence[str] = (),
        k: int | None = None,
        question_id: str | None = None,
    ) -> Answer:
        timings = StageTimings()
        k = k or self.config.k

        with timings.time("parse"):
            # The window is parsed here and again inside routing; parsing is
            # pure and cheap, and a separate stage timing is what the latency
            # report needs.
            window = parse_time_window(question, anchor=self.snapshot_anchor)

        with timings.time("route"):
            route = self.router.route(question)
            window = route.time_window
            # The temporal-fields ablation keeps this parsed window in the
            # report but stops _retrieve and _query_graph from using it; see
            # self.config.use_temporal_fields in both.

        hits: list[dict[str, Any]] = []
        with timings.time("retrieve"):
            if not route.should_abstain and self.config.documents_enabled:
                hits = self._retrieve(route, k=k)

        graph_results: list[GraphResult] = []
        trend_signals: list[TrendSignal] = []
        with timings.time("graph"):
            if not route.should_abstain and self.config.graph_enabled:
                graph_results, trend_signals = self._query_graph(route)

        with timings.time("generate"):
            answer = self._compose(
                question=question,
                question_id=question_id,
                route=route,
                window=window,
                hits=hits,
                graph_results=graph_results,
                trend_signals=trend_signals,
                requires=requires,
            )

        # Filled after the generate stage closes. Reading the timings inside the
        # context manager would leave generate unmeasured and silently charge
        # its time to "unattributed".
        answer.latency = timings.as_dict()

        if self.latency:
            self.latency.record(
                {
                    "question_id": question_id,
                    "question": question,
                    "intent": route.intent,
                    "mode": self.config.mode,
                    "routing_method": route.method,
                    "provider": answer.provider.provider,
                    "abstained": answer.abstained,
                    "citations": len(answer.citations),
                    "latency": answer.latency,
                    "snapshot": self.snapshot_id,
                }
            )
        return answer

    # -- stages ----------------------------------------------------------

    def _retrieve(self, route: RouteDecision, *, k: int) -> list[dict[str, Any]]:
        window = route.time_window
        # Over-retrieve, then filter by time, so time filtering cannot empty a
        # result set that had valid hits further down the ranking.
        candidates = self.retriever.search(
            route.question, k=k * 6, config=self.config.retrieval_config
        )
        if self.config.use_temporal_fields and window.basis != "none":
            in_window = [hit for hit in candidates if window.contains(hit["passage"].best_time)]
        else:
            in_window = list(candidates)

        if self.config.use_corroboration_weighting:
            in_window = _apply_corroboration_bonus(in_window, bonus=self.config.corroboration_bonus)
        return in_window[:k]

    def _query_graph(self, route: RouteDecision) -> tuple[list[GraphResult], list[TrendSignal]]:
        window = route.time_window
        companies = list(route.companies) or self.graph.companies()
        results: list[GraphResult] = []
        signals: list[TrendSignal] = []

        observed_from = window.start if self.config.use_temporal_fields else None
        observed_to = window.end if self.config.use_temporal_fields else None
        weeks = window.iso_weeks() if self.config.use_temporal_fields else None

        if "sector" in route.question.lower() and self.graph.sectors():
            results.append(
                self.graph.sector_attention(
                    observed_from=observed_from,
                    observed_to=observed_to,
                    minimum_voice_origins=self.evidence_config.minimum_independent_origins,
                )
            )

        for company_id in companies[: self.config.max_companies_queried]:
            results.append(
                self.graph.company_records(
                    company_id, observed_from=observed_from, observed_to=observed_to
                )
            )
            results.append(self.graph.independent_origins(company_id))
            if route.intent in {"mixed_temporal", "aggregate", "evidence_state"}:
                if observed_from and observed_to:
                    results.append(
                        self.graph.temporal_paths(
                            company_id, observed_from=observed_from, observed_to=observed_to
                        )
                    )
                for metric in route.metrics or ("commits",):
                    results.append(self.graph.trend_paths(company_id, metric=metric, weeks=weeks))

        wanted_weeks = set(weeks) if weeks else None
        wanted_metrics = set(route.metrics) if route.metrics else None
        if route.intent == "mixed_temporal" and wanted_metrics is not None:
            # A co-occurrence question needs both halves. Filtering strictly to
            # the metrics the wording mentions would drop the activity series
            # from "which startups increased hiring" and then report that no
            # activity signal exists, which is a filter artefact, not a finding.
            wanted_metrics |= {"commits", "new_postings"}

        # When the question names role families, the hiring half comes from
        # those family series. Without a named family the company total is used.
        wanted_families = set(route.role_families)
        for signal in self.trend_run.signals:
            if signal.company_id is None or signal.label == "insufficient_history":
                continue
            if companies and signal.company_id not in companies:
                continue
            if wanted_weeks is not None and signal.iso_week not in wanted_weeks:
                continue
            if wanted_metrics is not None and signal.metric not in wanted_metrics:
                continue
            if signal.entity_type not in {"company", "company_role_family"}:
                continue
            if signal.signal_family == "jobs" and wanted_families:
                if signal.entity_type != "company_role_family":
                    continue
                if signal.entity_id.rsplit(":", 1)[-1] not in wanted_families:
                    continue
            signals.append(signal)
        return results, _select_trend_signals(signals, self.config.max_trend_citations)

    def _compose(
        self,
        *,
        question: str,
        question_id: str | None,
        route: RouteDecision,
        window: TimeWindow,
        hits: Sequence[Mapping[str, Any]],
        graph_results: Sequence[GraphResult],
        trend_signals: Sequence[TrendSignal],
        requires: Sequence[str],
    ) -> Answer:
        citations = _build_citations(
            hits, graph_results, trend_signals, max_graph=self.config.max_graph_citations
        )
        graph_paths = [path for result in graph_results for path in result.paths][:12]

        snapshot = {
            "snapshot_id": self.snapshot_id,
            "snapshot_anchor": self.snapshot_anchor,
            "last_data_week": self.trend_run.last_data_week,
            "records": len(self.records),
            "demo_mode": self.config.demo_mode,
            "replayed_from_snapshot": True,
            "graph_backend": self.graph.name,
            "dense": self.retriever.dense.describe(),
        }

        if route.should_abstain:
            text = (
                "I cannot answer this from the frozen snapshot. "
                + route.rationale
                + "."
            )
            return self._finish(
                question=question,
                question_id=question_id,
                answer_text=text,
                claims=[],
                citations=[],
                route=route,
                window=window,
                graph_results=list(graph_results),
                graph_paths=[],
                trend_signals=[],
                abstained=True,
                abstention_reason=route.rationale,
                missing_evidence=["evidence from the requested period"],
                qualified=False,
                qualification=None,
                provider=ProviderResult(text=text, provider="abstention"),
                snapshot=snapshot,
            )

        if not citations:
            missing = list(requires) or ["any record matching the question in this time window"]
            text = (
                "The snapshot contains no evidence that answers this question for "
                f"{window.label}. Missing: {', '.join(missing)}."
            )
            return self._finish(
                question=question,
                question_id=question_id,
                answer_text=text,
                claims=[],
                citations=[],
                route=route,
                window=window,
                graph_results=list(graph_results),
                graph_paths=graph_paths,
                trend_signals=[],
                abstained=True,
                abstention_reason="retrieval returned no evidence inside the requested time window",
                missing_evidence=missing,
                qualified=False,
                qualification=None,
                provider=ProviderResult(text=text, provider="abstention"),
                snapshot=snapshot,
            )

        findings = self._findings(route, window, citations, trend_signals, graph_results)
        context = {
            "snapshot_anchor": self.snapshot_anchor,
            "time_window_label": window.label,
            "time_window_start": window.start,
            "time_window_end": window.end,
            "intent": route.intent,
            "graph_summary": _graph_summary(graph_results),
            "trend_summary": _trend_summary(trend_signals, window),
            "findings": findings,
        }
        evidence_items = [citation.as_dict() for citation in citations]
        try:
            result = self.provider.generate(question, evidence_items, context=context)
        except RuntimeError as exc:
            # A provider failure must not fabricate an answer; fall back to the
            # extractive composer and say why in the bundle.
            result = ExtractiveProvider().generate(question, evidence_items, context=context)
            result = ProviderResult(
                text=result.text,
                provider="extractive",
                fallback_used=True,
                fallback_reason=str(exc),
            )
        if self.provider_fallback_reason and not result.fallback_used:
            result = ProviderResult(
                text=result.text,
                provider=result.provider,
                model=result.model,
                fallback_used=True,
                fallback_reason=self.provider_fallback_reason,
                usage=result.usage,
                refused=result.refused,
            )

        by_number = {citation.number: citation for citation in citations}
        evidence_config = (
            self.evidence_config
            if self.config.use_temporal_fields
            else _timeless(self.evidence_config)
        )
        claims: list[Claim] = []
        for text, numbers in split_claims(result.text):
            supporting = [by_number[number] for number in numbers if number in by_number]
            claims.append(
                Claim(
                    text=text,
                    citation_numbers=tuple(numbers),
                    # No `requires` here: the evidence kinds a question needs are
                    # a property of the question, not of each sentence, and
                    # applying them per claim would report github as missing
                    # from a sentence about hiring even when the answer cites
                    # both.
                    assessment=assess_evidence(
                        supporting,
                        snapshot_anchor=self.snapshot_anchor,
                        config=evidence_config,
                    ),
                )
            )

        supported = [claim for claim in claims if claim.supported]
        overall = worst_state([claim.assessment.state for claim in claims]) if claims else "insufficient"
        # The question's requirements are checked once, against everything the
        # answer cites.
        missing = list(
            assess_evidence(
                [by_number[number] for claim in supported for number in claim.citation_numbers if number in by_number]
                or citations,
                snapshot_anchor=self.snapshot_anchor,
                config=evidence_config,
                requires=requires,
            ).missing_evidence
        )

        if not supported:
            return self._finish(
                question=question,
                question_id=question_id,
                answer_text=(
                    "I cannot support an answer to this question from the retrieved evidence. "
                    + (f"Missing: {', '.join(missing)}." if missing else "No claim could be cited.")
                ),
                claims=claims,
                citations=citations,
                route=route,
                window=window,
                graph_results=list(graph_results),
                graph_paths=graph_paths,
                trend_signals=list(trend_signals),
                abstained=True,
                abstention_reason="no claim in the generated answer was supported by cited evidence",
                missing_evidence=missing or ["cited support for at least one claim"],
                qualified=False,
                qualification=None,
                provider=result,
                snapshot=snapshot,
            )

        qualification = None
        if missing:
            qualification = (
                "Partial evidence: the answer rests on "
                f"{len(supported)} supported claim(s), but {', '.join(missing)} "
                "is not present in this snapshot, so the answer is qualified rather than complete."
            )
        elif overall in {"emerging", "disputed", "stale"}:
            qualification = _state_qualification(overall)

        return self._finish(
            question=question,
            question_id=question_id,
            answer_text=result.text,
            claims=claims,
            citations=citations,
            route=route,
            window=window,
            graph_results=list(graph_results),
            graph_paths=graph_paths,
            trend_signals=list(trend_signals),
            abstained=False,
            abstention_reason=None,
            missing_evidence=missing,
            qualified=qualification is not None,
            qualification=qualification,
            provider=result,
            snapshot=snapshot,
        )

    def _findings(
        self,
        route: RouteDecision,
        window: TimeWindow,
        citations: Sequence[Citation],
        trend_signals: Sequence[TrendSignal],
        graph_results: Sequence[GraphResult] = (),
    ) -> list[dict[str, Any]]:
        """Statements that answer the question, derived from cited evidence.

        Findings exist because retrieved excerpts are not an answer to an
        aggregate or multi-signal question. Each one is computed from the trend
        signals and graph rows the answer already cites, and carries those
        citation numbers, so a finding is never an uncited assertion.
        """
        trend_citations = {
            citation.detail.get("trend_id"): citation.number
            for citation in citations
            if citation.kind == "trend"
        }
        findings: list[dict[str, Any]] = []

        if route.intent in {"mixed_temporal", "aggregate"} and trend_signals:
            by_company: dict[str, dict[str, list[TrendSignal]]] = {}
            for signal in trend_signals:
                if signal.company_id is None:
                    continue
                family = by_company.setdefault(signal.company_id, {})
                family.setdefault(signal.signal_family, []).append(signal)

            for company_id in sorted(by_company):
                families = by_company[company_id]
                activity = [
                    signal
                    for signal in families.get("github", [])
                    if signal.label in {"rising", "falling"}
                ]
                hiring = [
                    signal
                    for signal in families.get("jobs", [])
                    if signal.value and signal.value > 0
                ]
                numbers = tuple(
                    sorted(
                        trend_citations[signal.trend_id]
                        for signal in activity + hiring
                        if signal.trend_id in trend_citations
                    )
                )
                if not numbers:
                    continue
                if activity and hiring:
                    text = (
                        f"{company_id} shows both signals in this window: "
                        + ", ".join(
                            f"{signal.metric} {signal.label} in {signal.iso_week} "
                            f"(score {signal.trend_score:.2f})"
                            for signal in activity[:2]
                            if signal.trend_score is not None
                        )
                        + "; and "
                        + ", ".join(
                            f"{int(signal.value)} new {_hiring_label(signal)} posting(s) in "
                            f"{signal.iso_week}"
                            for signal in hiring[:2]
                        )
                        + "."
                    )
                elif activity:
                    signal = activity[0]
                    text = (
                        f"{company_id} shows {signal.metric} {signal.label} in {signal.iso_week} "
                        f"(score {signal.trend_score:.2f}), but no matching hiring signal in this "
                        "window."
                        if signal.trend_score is not None
                        else f"{company_id} shows {signal.metric} {signal.label} in {signal.iso_week}."
                    )
                else:
                    signal = hiring[0]
                    text = (
                        f"{company_id} has {int(signal.value)} new {_hiring_label(signal)} "
                        f"posting(s) in {signal.iso_week}, but no rising development-activity "
                        "signal in this window."
                    )
                findings.append({"text": text, "citation_numbers": list(numbers)})

        if route.intent == "evidence_state":
            by_company: dict[str, list[Citation]] = {}
            for citation in citations:
                if citation.kind == "passage" and citation.company_id:
                    by_company.setdefault(citation.company_id, []).append(citation)
            for company_id in sorted(by_company)[:3]:
                group = by_company[company_id]
                assessment = assess_evidence(group, snapshot_anchor=self.snapshot_anchor, config=self.evidence_config)
                change = {
                    "emerging": "a second independent origin, or one operational signal alongside it",
                    "corroborated": "a credible source disagreeing on a material value would move it to disputed",
                    "disputed": "agreement between the conflicting origins, or a third independent origin",
                    "stale": "a fresh snapshot inside the refresh window",
                    "insufficient": "any record that supports the claim",
                }[assessment.state]
                findings.append(
                    {
                        "text": (
                            f"Evidence retrieved about {company_id} in this window is "
                            f"{assessment.state}: {assessment.reason}. "
                            f"What would change it: {change}."
                        ),
                        "citation_numbers": [citation.number for citation in group[:3]],
                    }
                )

        if "sector" in route.question.lower():
            sector_result = next(
                (result for result in graph_results if result.purpose == "sector_attention"), None
            )
            numbered = [citation.number for citation in citations if citation.kind == "graph"][:1]
            if sector_result is None or not sector_result.rows:
                # Without Sector nodes the question cannot be grouped by sector.
                # Saying so beats grouping by company and calling it a sector
                # answer.
                findings.append(
                    {
                        "text": (
                            "The graph holds no Sector nodes, so this answer cannot be grouped by "
                            "sector; what follows is per-company evidence for the same window."
                        ),
                        "citation_numbers": numbered,
                    }
                )
            else:
                for row in sector_result.rows:
                    name = row["sector_id"].replace("_", " ")
                    if row["qualifies"]:
                        text = (
                            f"The {name} sector qualifies: "
                            f"{row['independent_voice_origins']} independent coverage origins "
                            f"across {len(row['companies'])} cohort companies, and "
                            f"{row['operational_records']} operational records in the same window."
                        )
                    else:
                        reason = (
                            f"only {row['independent_voice_origins']} independent coverage "
                            f"origin(s)"
                            if row["independent_voice_origins"]
                            < self.evidence_config.minimum_independent_origins
                            else "no operational signal in the window"
                        )
                        text = (
                            f"The {name} sector does not qualify: {reason} across "
                            f"{len(row['companies'])} cohort companies."
                        )
                    findings.append({"text": text, "citation_numbers": numbered})

        return findings

    def _finish(self, **kwargs: Any) -> Answer:
        claims = kwargs.pop("claims")
        kwargs["time_window"] = kwargs.pop("window")
        overall = worst_state([claim.assessment.state for claim in claims]) if claims else "insufficient"
        return Answer(
            claims=claims,
            overall_state=overall,
            # Replaced by answer() once the generate stage has closed.
            latency={},
            config={
                **self.config.as_dict(),
                "evidence": self.evidence_config.as_dict(),
                "retrieval": self.retriever.describe(),
                "router": self.router.describe(),
            },
            **kwargs,
        )

    # -- helpers ---------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_anchor": self.snapshot_anchor,
            "records": len(self.records),
            "config": self.config.as_dict(),
            "provider": self.provider.name,
            "provider_fallback_reason": self.provider_fallback_reason,
            "retrieval": self.retriever.describe(),
            "graph": self.graph.describe(),
            "router": self.router.describe(),
            "trend": {
                "series": len(self.trend_run.bundle.series),
                "signals": len(self.trend_run.signals),
                "labels": self.trend_run.labels(),
                "last_data_week": self.trend_run.last_data_week,
            },
        }


def _select_trend_signals(
    signals: Sequence[TrendSignal], budget: int
) -> list[TrendSignal]:
    """Pick which trend signals to cite, fairly across signal families.

    Ranking strictly by score would spend the whole budget on the loudest
    family -- a question about both development activity and hiring would cite
    only commits and then report, wrongly, that no hiring signal exists. So the
    budget is shared: each family is ordered with its rising and falling weeks
    first and the strongest scores next, and the families are then taken in
    turn.
    """
    by_family: dict[str, list[TrendSignal]] = {}
    for signal in signals:
        by_family.setdefault(signal.signal_family, []).append(signal)
    for family in by_family.values():
        family.sort(
            key=lambda item: (
                0 if item.label in {"rising", "falling"} else 1,
                -abs(item.trend_score or 0.0),
                item.company_id or "",
                item.metric,
                item.iso_week,
            )
        )
    selected: list[TrendSignal] = []
    index = 0
    order = sorted(by_family)
    while len(selected) < budget and any(index < len(by_family[name]) for name in order):
        for name in order:
            if index < len(by_family[name]) and len(selected) < budget:
                selected.append(by_family[name][index])
        index += 1
    selected.sort(key=lambda item: (item.company_id or "", item.signal_family, item.metric, item.iso_week))
    return selected


def _hiring_label(signal: TrendSignal) -> str:
    """Name the hiring series in prose: the role family, or the company total."""
    if signal.entity_type == "company_role_family":
        return signal.entity_id.rsplit(":", 1)[-1]
    return "job"


def _timeless(config: EvidenceConfig) -> EvidenceConfig:
    """Evidence config with staleness effectively disabled.

    Used by the temporal-fields ablation so "no temporal fields" really means
    the answer cannot use time, rather than using it in one place only.
    """
    return EvidenceConfig(
        minimum_independent_origins=config.minimum_independent_origins,
        amount_tolerance=config.amount_tolerance,
        date_tolerance_days=config.date_tolerance_days,
        refresh_window_days=10**6,
        allowed_missed_refresh_windows=1,
    )


def _snapshot_anchor(records: Sequence[Mapping[str, Any]]) -> str:
    latest = None
    for record in records:
        observed = record.get("observed_at")
        if not observed:
            continue
        instant = parse_instant(observed)
        if latest is None or instant > latest:
            latest = instant
    if latest is None:
        raise ValueError("cannot determine a snapshot anchor: no record carries observed_at")
    from signals.weeks import format_instant

    return format_instant(latest)


def _encoder(spec: str | None):
    if spec is None:
        return None
    from retrieval.dense import build_encoder

    return build_encoder(spec)


def _apply_corroboration_bonus(
    hits: Sequence[Mapping[str, Any]], *, bonus: float
) -> list[dict[str, Any]]:
    """Prefer passages about a company that several independent origins cover.

    This is a ranking preference only. It never changes the evidence state of a
    claim, which follows the ledger's rules regardless of how the passage was
    ranked, so the ablation isolates ranking from state assignment.
    """
    origins_by_company: dict[str | None, set[str]] = {}
    for hit in hits:
        passage: Passage = hit["passage"]
        origins_by_company.setdefault(passage.company_id, set()).add(passage.origin_cluster_id)

    adjusted: list[dict[str, Any]] = []
    for hit in hits:
        passage = hit["passage"]
        corroborating = len(origins_by_company.get(passage.company_id, set()))
        item = dict(hit)
        item["corroborating_origins"] = corroborating
        if corroborating > 1:
            item["score"] = hit["score"] * (1.0 + bonus)
            item["corroboration_bonus_applied"] = True
        else:
            item["corroboration_bonus_applied"] = False
        adjusted.append(item)
    adjusted.sort(key=lambda hit: (-hit["score"], hit["passage_id"]))
    return adjusted


def _build_citations(
    hits: Sequence[Mapping[str, Any]],
    graph_results: Sequence[GraphResult],
    trend_signals: Sequence[TrendSignal],
    *,
    max_graph: int = 3,
) -> list[Citation]:
    citations: list[Citation] = []
    number = 1
    for hit in hits:
        passage: Passage = hit["passage"]
        citations.append(
            Citation(
                number=number,
                kind="passage",
                record_ids=(passage.record_id,),
                origin_cluster_ids=(passage.origin_cluster_id,),
                source_type=passage.source_type,
                title=passage.title,
                source_url=passage.source_url,
                publisher=passage.publisher,
                company_id=passage.company_id,
                when=passage.best_time,
                time_basis=passage.time_basis,
                text=passage.text,
                retrievers=dict(hit.get("retrievers") or {}),
                score=float(hit.get("score") or 0.0),
                detail={
                    "corroborating_origins": hit.get("corroborating_origins"),
                    "corroboration_bonus_applied": hit.get("corroboration_bonus_applied"),
                },
            )
        )
        number += 1

    for signal in trend_signals:
        # Zero-filled weekly bins describe missing observations. They have no
        # documentary origin and cannot serve as factual supporting evidence.
        if not signal.origin_cluster_ids or not signal.record_ids:
            continue
        citations.append(
            Citation(
                number=number,
                kind="trend",
                record_ids=tuple(signal.record_ids),
                origin_cluster_ids=tuple(signal.origin_cluster_ids),
                source_type={"github": "github", "jobs": "job", "news": "news"}.get(signal.signal_family),
                title=f"{signal.metric} {signal.label} in {signal.iso_week}",
                source_url=None,
                publisher=None,
                company_id=signal.company_id,
                when=signal.week_end,
                time_basis="iso_week",
                text=(
                    f"{signal.entity_id} {signal.metric} was {signal.value} in {signal.iso_week} "
                    f"against an EWMA baseline of "
                    f"{'n/a' if signal.ewma_baseline is None else round(signal.ewma_baseline, 2)} "
                    f"(label {signal.label}, score "
                    f"{'n/a' if signal.trend_score is None else round(signal.trend_score, 2)}). "
                    "This describes observed activity, not a prediction."
                ),
                detail={
                    "trend_id": signal.trend_id,
                    "series_id": signal.series_id,
                    "label": signal.label,
                    "trend_score": signal.trend_score,
                    "iso_week": signal.iso_week,
                },
            )
        )
        number += 1

    graph_citations = 0
    for result in graph_results:
        rows = [row for row in result.rows if row]
        if not rows:
            continue
        if result.purpose not in {"independent_origins", "temporal_multihop", "trend_signals"}:
            continue
        # An aggregate with zero supporting origins is useful graph context,
        # but cannot support a factual claim as a numbered citation.
        if not any(row.get("origin_cluster_ids") or row.get("origin_cluster_id") for row in rows):
            continue
        if graph_citations >= max_graph:
            break
        graph_citations += 1
        citations.append(
            Citation(
                number=number,
                kind="graph",
                record_ids=tuple(
                    str(row["record_id"]) for row in rows if row.get("record_id")
                ),
                origin_cluster_ids=tuple(
                    origin
                    for row in rows
                    for origin in (row.get("origin_cluster_ids") or ([row["origin_cluster_id"]] if row.get("origin_cluster_id") else []))
                ),
                source_type=None,
                title=result.template.description if result.template else result.purpose,
                source_url=None,
                publisher=None,
                company_id=str(rows[0].get("company_id")) if rows[0].get("company_id") else None,
                when=None,
                time_basis=None,
                text=json.dumps(rows[:3], sort_keys=True, default=str),
                detail={
                    "purpose": result.purpose,
                    "cypher_name": result.template.name if result.template else None,
                    "backend": result.backend,
                    "note": result.note,
                },
            )
        )
        number += 1
    return citations


def _graph_summary(graph_results: Sequence[GraphResult]) -> str | None:
    parts = []
    for result in graph_results:
        if result.purpose == "independent_origins" and result.rows:
            row = result.rows[0]
            parts.append(f"{row['company_id']}: {row['independent_origins']} independent origins")
    return "; ".join(parts[:6]) or None


def _trend_summary(trend_signals: Sequence[TrendSignal], window: TimeWindow) -> str | None:
    rising = [signal for signal in trend_signals if signal.label == "rising"]
    falling = [signal for signal in trend_signals if signal.label == "falling"]
    if not rising and not falling:
        return None
    parts = []
    for signal in rising[:5]:
        parts.append(f"{signal.company_id} {signal.metric} rising in {signal.iso_week}")
    for signal in falling[:3]:
        parts.append(f"{signal.company_id} {signal.metric} falling in {signal.iso_week}")
    return "; ".join(parts)


def _state_qualification(state: str) -> str:
    return {
        "emerging": (
            "Qualified: the strongest claim rests on a single independent origin, which the "
            "evidence ledger treats as emerging rather than established."
        ),
        "disputed": (
            "Qualified: independent origins disagree on a material value. The conflict is shown "
            "rather than resolved."
        ),
        "stale": (
            "Qualified: the supporting operational snapshots are older than the allowed refresh "
            "windows, so the answer describes a period that may have moved on."
        ),
    }[state]


__all__ = [
    "ANSWER_SCHEMA_PATH",
    "RETRIEVAL_MODES",
    "AgentConfig",
    "Answer",
    "Citation",
    "Claim",
    "TrendScoutAgent",
    "validate_answer",
]
