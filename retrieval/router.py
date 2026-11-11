"""Query router: intent, time window, and which retrievers to run.

Routing follows the proposal: exact and aggregate questions go to Cypher,
narrative questions go to document retrieval, mixed temporal questions go to
both, evidence-state questions go to the ledger, and questions the snapshot
cannot answer at all are routed to abstention before any retrieval runs.

Two methods, both classical
---------------------------
``rules``
    Ordered pattern rules. The default, because it is inspectable: every
    decision names the rule that produced it.

``tfidf_logistic``
    The proposal's other classical baseline: TF-IDF features and a multinomial
    logistic regression trained on the labelled development questions in
    :data:`TRAINING_QUESTIONS`. Implemented here in plain Python -- no
    scikit-learn -- so it trains in milliseconds and runs wherever the tests
    run. Deterministic: zero initialisation, fixed epochs, fixed learning rate.

Both methods are overridden by one hard constraint. A question about a period
after the snapshot cannot be answered from the snapshot however it is retrieved,
so :func:`~retrieval.timewindow.mentions_future` sends it straight to
``unsupported``. That is a property of the data, not a guess about intent.

The 60 training questions are a development set written by the team. They are
enough to separate these six intents on the seed questions; they are not an
evaluation set, and the classifier's accuracy on them is not a result.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from retrieval.timewindow import TimeWindow, mentions_future, parse_time_window

INTENTS: tuple[str, ...] = (
    "exact",
    "aggregate",
    "narrative",
    "mixed_temporal",
    "evidence_state",
    "unsupported",
)

ROUTING_METHODS: tuple[str, ...] = ("rules", "tfidf_logistic")

#: Which retrieval strategies each intent activates.
INTENT_STRATEGIES: dict[str, tuple[str, ...]] = {
    "exact": ("graph",),
    "aggregate": ("graph", "trend"),
    "narrative": ("documents",),
    "mixed_temporal": ("graph", "documents", "trend"),
    "evidence_state": ("graph", "ledger"),
    "unsupported": (),
}

_WORD = re.compile(r"[a-z0-9]+")

# Vocabulary that marks a question as being about operational signals, which is
# what makes a temporal question "mixed" rather than purely narrative.
OPERATIONAL_TERMS: frozenset[str] = frozenset(
    {
        "github",
        "commits",
        "commit",
        "repository",
        "repositories",
        "repo",
        "repos",
        "stars",
        "activity",
        "hiring",
        "hire",
        "hires",
        "job",
        "jobs",
        "posting",
        "postings",
        "role",
        "roles",
        "skill",
        "skills",
        "mlops",
        "retrieval",
        "evaluation",
        "funding",
        "raised",
        "round",
        "investor",
        "investors",
        "trend",
        "trends",
        "trending",
        "rising",
        "falling",
        "momentum",
        "signal",
        "signals",
    }
)

EVIDENCE_STATE_TERMS: frozenset[str] = frozenset(
    {"emerging", "corroborated", "disputed", "stale", "insufficient", "ledger", "abstain"}
)


@dataclass(frozen=True)
class RouteDecision:
    """Where a question is sent, and why."""

    question: str
    intent: str
    strategies: tuple[str, ...]
    time_window: TimeWindow
    confidence: float
    method: str
    rationale: str
    matched_rules: tuple[str, ...] = ()
    scores: Mapping[str, float] = field(default_factory=dict)
    companies: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    future_reference: str | None = None

    @property
    def should_abstain(self) -> bool:
        return self.intent == "unsupported"

    def uses(self, strategy: str) -> bool:
        return strategy in self.strategies

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "strategies": list(self.strategies),
            "time_window": self.time_window.as_dict(),
            "confidence": self.confidence,
            "method": self.method,
            "rationale": self.rationale,
            "matched_rules": list(self.matched_rules),
            "scores": dict(self.scores),
            "companies": list(self.companies),
            "metrics": list(self.metrics),
            "future_reference": self.future_reference,
        }


# ---------------------------------------------------------------------------
# Rule-based intent
# ---------------------------------------------------------------------------

#: ``(rule name, intent, pattern, confidence)``, evaluated in order.
INTENT_RULES: tuple[tuple[str, str, str, float], ...] = (
    (
        "prediction",
        "unsupported",
        r"\b(will|would|going to|predict|prediction|forecast|expect to|likely to|"
        r"guarantee|future|projected)\b",
        0.95,
    ),
    (
        "evidence_state_vocabulary",
        "evidence_state",
        r"\b(emerging|corroborated|disputed|stale|insufficient evidence|evidence state|"
        r"evidence status|evidence ledger)\b",
        0.9,
    ),
    (
        "why_marked",
        "evidence_state",
        r"\bwhy (is|was|are|were)\b.*\b(marked|labelled|labeled|classified|considered)\b",
        0.9,
    ),
    (
        "what_evidence_would_change",
        "evidence_state",
        r"\bwhat (evidence|would it take)\b.*\b(change|different|revise)\b",
        0.85,
    ),
    (
        "aggregate_counting",
        "aggregate",
        r"\b(how many|how much|count|total|number of|average|median)\b",
        0.85,
    ),
    (
        "aggregate_ranking",
        "aggregate",
        r"\b(top|most|least|highest|lowest|rank|ranked|ranking|compare|which companies|"
        r"which startups|list all)\b",
        0.7,
    ),
    (
        "multi_signal",
        "mixed_temporal",
        r"\b(both|and also|as well as|while also|combined with|together with|later)\b",
        0.8,
    ),
    (
        "exact_lookup",
        "exact",
        r"\b(who|when did|what is the|which investor|how is .* linked|what repositories)\b",
        0.65,
    ),
    (
        "narrative_explanation",
        "narrative",
        r"\b(why|how|explain|describe|what happened|tell me about|what are they doing|summary)\b",
        0.6,
    ),
)


def tokenize(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _features(text: str) -> list[str]:
    words = tokenize(text)
    return words + [f"{left}_{right}" for left, right in zip(words, words[1:])]


def detect_companies(question: str, company_ids: Iterable[str], aliases: Mapping[str, Sequence[str]] | None = None) -> tuple[str, ...]:
    """Cohort companies named in a question, by id or alias.

    Matching is on explicit mentions only, consistent with how the collectors
    link records to companies.
    """
    lowered = f" {' '.join(tokenize(question))} "
    found: list[str] = []
    for company_id in company_ids:
        needles = [company_id.replace("-", " "), company_id.replace("-", "")]
        for alias in (aliases or {}).get(company_id, ()):  # type: ignore[arg-type]
            needles.append(" ".join(tokenize(alias)))
        if any(needle and f" {needle} " in lowered for needle in needles):
            found.append(company_id)
    return tuple(dict.fromkeys(found))


def detect_metrics(question: str) -> tuple[str, ...]:
    """Trend metrics a question refers to, for selecting series."""
    lowered = set(tokenize(question))
    metrics: list[str] = []
    if lowered & {"commit", "commits", "activity", "github", "development", "repository", "repositories"}:
        metrics.append("commits")
    if lowered & {"star", "stars"}:
        metrics.append("star_delta")
    if lowered & {"hiring", "hire", "hires", "job", "jobs", "posting", "postings", "roles", "role"}:
        metrics.append("new_postings")
    if lowered & {"news", "coverage", "attention", "press", "voices"}:
        metrics.append("distinct_origins")
    return tuple(dict.fromkeys(metrics))


def classify_with_rules(question: str) -> tuple[str, float, tuple[str, ...], str]:
    """Return ``(intent, confidence, matched rules, rationale)``."""
    text = (question or "").lower()
    matched: list[tuple[str, str, float]] = []
    for name, intent, pattern, confidence in INTENT_RULES:
        if re.search(pattern, text):
            matched.append((name, intent, confidence))
    if not matched:
        return (
            "narrative",
            0.4,
            (),
            "no intent rule matched; defaulting to document retrieval",
        )

    name, intent, confidence = matched[0]
    rule_names = tuple(item[0] for item in matched)

    # A temporal question that also mentions operational signals needs both the
    # graph and the documents, whichever single rule fired first.
    has_time = bool(parse_time_window(question, anchor="2000-01-01T00:00:00Z").basis != "none")
    operational = set(tokenize(question)) & OPERATIONAL_TERMS
    if intent in {"narrative", "aggregate", "exact"} and has_time and operational:
        return (
            "mixed_temporal",
            max(confidence, 0.8),
            rule_names + ("temporal_with_operational_signal",),
            f"rule {name!r} matched, and the question combines a time window with "
            f"operational signals ({', '.join(sorted(operational))}), so both the graph and "
            "the documents are needed",
        )
    return (
        intent,
        confidence,
        rule_names,
        f"rule {name!r} matched" + (f" (also: {', '.join(rule_names[1:])})" if len(rule_names) > 1 else ""),
    )


# ---------------------------------------------------------------------------
# TF-IDF + logistic regression baseline
# ---------------------------------------------------------------------------

#: Labelled development questions. Team-authored; not an evaluation set.
TRAINING_QUESTIONS: tuple[tuple[str, str], ...] = (
    # exact
    ("Who invested in LangChain", "exact"),
    ("When did CrewAI raise its seed round", "exact"),
    ("What is the default branch of the langchain repository", "exact"),
    ("Which investor funded LlamaIndex", "exact"),
    ("What repositories does CrewAI maintain", "exact"),
    ("When was the LangSmith announcement published", "exact"),
    ("Who published the CrewAI interview", "exact"),
    ("What is the source url for the LlamaIndex blog post", "exact"),
    ("Which company owns the stagehand repository", "exact"),
    ("When did LangChain last post a job for an evaluation engineer", "exact"),
    # aggregate
    ("How many independent origins cover LangChain", "aggregate"),
    ("How many open postings does CrewAI have", "aggregate"),
    ("Which companies have the most GitHub activity", "aggregate"),
    ("Rank the cohort by distinct news origins", "aggregate"),
    ("What is the total number of job postings in the cohort", "aggregate"),
    ("Compare LangChain and LlamaIndex by commit volume", "aggregate"),
    ("Which startups have the highest number of MLOps postings", "aggregate"),
    ("Count the records collected for each company", "aggregate"),
    ("List all companies with a public GitHub organisation", "aggregate"),
    ("What is the average weekly commit count for LlamaIndex", "aggregate"),
    # narrative
    ("Why is CrewAI interesting to developers", "narrative"),
    ("Explain what LangSmith does", "narrative"),
    ("Describe the LlamaIndex document agent pattern", "narrative"),
    ("What happened with the LangChain funding announcement", "narrative"),
    ("Tell me about agent infrastructure startups", "narrative"),
    ("How does CrewAI describe its orchestration approach", "narrative"),
    ("Summarise the coverage of LlamaIndex", "narrative"),
    ("What are the public voices saying about multi agent systems", "narrative"),
    ("Explain the difference between the cohort categories", "narrative"),
    ("What is the stated purpose of the LangGraph project", "narrative"),
    # mixed temporal
    ("Which agent infrastructure startups show both rising GitHub activity and new MLOps hiring during the last eight weeks", "mixed_temporal"),
    ("Which investors funded startups that later increased hiring for retrieval or evaluation skills", "mixed_temporal"),
    ("Which sectors gained attention from multiple public voices and also produced operational signals", "mixed_temporal"),
    ("Which companies increased commits and news coverage in the last month", "mixed_temporal"),
    ("Did LangChain hiring grow after its funding round", "mixed_temporal"),
    ("Which startups show rising repository activity over the last twelve weeks", "mixed_temporal"),
    ("Show companies whose hiring and GitHub signals both rose since September", "mixed_temporal"),
    ("Which companies had new retrieval postings in the last quarter and press coverage", "mixed_temporal"),
    ("Has CrewAI activity risen in the last eight weeks", "mixed_temporal"),
    ("Which companies slowed down in commits during the last month", "mixed_temporal"),
    ("Which startups combined funding news with repository growth this quarter", "mixed_temporal"),
    ("Track MLOps hiring against commit trends for the cohort over the last ten weeks", "mixed_temporal"),
    # evidence state
    ("Why is a company marked as emerging", "evidence_state"),
    ("What evidence would change the emerging label", "evidence_state"),
    ("Which claims about LangChain are corroborated", "evidence_state"),
    ("Is the CrewAI funding claim disputed", "evidence_state"),
    ("Why is this claim stale", "evidence_state"),
    ("Show the evidence state for the LlamaIndex claim", "evidence_state"),
    ("What does corroborated mean for this answer", "evidence_state"),
    ("Which claims have insufficient evidence", "evidence_state"),
    ("Why was the funding amount considered disputed", "evidence_state"),
    ("Explain the evidence ledger entry for LangSmith", "evidence_state"),
    # unsupported
    ("Which company in the cohort will have the highest valuation in 2027", "unsupported"),
    ("Which frozen cohort company acquired Anthropic in 2024", "unsupported"),
    ("Will CrewAI be acquired next year", "unsupported"),
    ("Predict the commit volume for next quarter", "unsupported"),
    ("Which startup is going to fail", "unsupported"),
    ("What will hiring look like going forward", "unsupported"),
    ("Forecast the number of releases next month", "unsupported"),
    ("Which company is likely to raise a Series C next", "unsupported"),
)


@dataclass
class TfidfLogisticIntentClassifier:
    """Multinomial logistic regression over TF-IDF features, in plain Python."""

    training: Sequence[tuple[str, str]] = TRAINING_QUESTIONS
    epochs: int = 400
    learning_rate: float = 0.5
    l2: float = 1e-4
    labels: tuple[str, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        documents = [_features(question) for question, _ in self.training]
        targets = [label for _, label in self.training]
        self.labels = tuple(sorted(set(targets)))

        document_frequency: dict[str, int] = {}
        for features in documents:
            for feature in set(features):
                document_frequency[feature] = document_frequency.get(feature, 0) + 1
        total = len(documents)
        self.idf = {
            feature: math.log((1 + total) / (1 + count)) + 1.0
            for feature, count in document_frequency.items()
        }
        self.vocabulary = {feature: index for index, feature in enumerate(sorted(self.idf))}

        vectors = [self._vector(features) for features in documents]
        label_index = {label: index for index, label in enumerate(self.labels)}
        self.weights = [[0.0] * len(self.vocabulary) for _ in self.labels]
        self.bias = [0.0] * len(self.labels)

        for _ in range(self.epochs):
            weight_gradient = [[0.0] * len(self.vocabulary) for _ in self.labels]
            bias_gradient = [0.0] * len(self.labels)
            for vector, target in zip(vectors, targets):
                probabilities = self._softmax(vector)
                for index, label in enumerate(self.labels):
                    error = probabilities[index] - (1.0 if label_index[target] == index else 0.0)
                    if error == 0.0:
                        continue
                    row = weight_gradient[index]
                    for feature_index, value in vector.items():
                        row[feature_index] += error * value
                    bias_gradient[index] += error
            scale = self.learning_rate / len(vectors)
            for index in range(len(self.labels)):
                row, gradient = self.weights[index], weight_gradient[index]
                for feature_index in range(len(row)):
                    row[feature_index] -= scale * (gradient[feature_index] + self.l2 * row[feature_index])
                self.bias[index] -= scale * bias_gradient[index]

    def _vector(self, features: Sequence[str]) -> dict[int, float]:
        counts: dict[str, int] = {}
        for feature in features:
            if feature in self.vocabulary:
                counts[feature] = counts.get(feature, 0) + 1
        raw = {
            self.vocabulary[feature]: (1.0 + math.log(count)) * self.idf[feature]
            for feature, count in counts.items()
        }
        norm = math.sqrt(sum(value * value for value in raw.values()))
        if norm == 0.0:
            return raw
        return {index: value / norm for index, value in raw.items()}

    def _softmax(self, vector: Mapping[int, float]) -> list[float]:
        logits = []
        for index in range(len(self.labels)):
            row = self.weights[index]
            logits.append(self.bias[index] + sum(row[key] * value for key, value in vector.items()))
        highest = max(logits)
        exponentials = [math.exp(value - highest) for value in logits]
        total = sum(exponentials)
        return [value / total for value in exponentials]

    def predict(self, question: str) -> tuple[str, float, dict[str, float]]:
        vector = self._vector(_features(question))
        probabilities = self._softmax(vector)
        scores = {label: probabilities[index] for index, label in enumerate(self.labels)}
        best = max(scores, key=lambda label: scores[label])
        return best, scores[best], scores

    def training_accuracy(self) -> float:
        """Fit on the development set. Not a result; a sanity check."""
        correct = sum(
            1 for question, label in self.training if self.predict(question)[0] == label
        )
        return correct / len(self.training)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass
class QueryRouter:
    """Resolve intent, time window, and strategies for a question."""

    snapshot_anchor: str
    method: str = "rules"
    company_ids: Sequence[str] = ()
    aliases: Mapping[str, Sequence[str]] = field(default_factory=dict)
    coverage_start: str | None = None
    _classifier: TfidfLogisticIntentClassifier | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.method not in ROUTING_METHODS:
            raise ValueError(f"unsupported routing method: {self.method}")

    @property
    def classifier(self) -> TfidfLogisticIntentClassifier:
        if self._classifier is None:
            self._classifier = TfidfLogisticIntentClassifier()
        return self._classifier

    def route(self, question: str, *, method: str | None = None) -> RouteDecision:
        method = method or self.method
        if method not in ROUTING_METHODS:
            raise ValueError(f"unsupported routing method: {method}")

        window = parse_time_window(question, anchor=self.snapshot_anchor)
        future = mentions_future(question, anchor=self.snapshot_anchor)
        companies = detect_companies(question, self.company_ids, self.aliases)
        metrics = detect_metrics(question)

        if future:
            return RouteDecision(
                question=question,
                intent="unsupported",
                strategies=INTENT_STRATEGIES["unsupported"],
                time_window=window,
                confidence=1.0,
                method=f"{method}+snapshot_bound",
                rationale=(
                    f"the question refers to {future!r}, which is after the snapshot anchor "
                    f"{self.snapshot_anchor}; no retrieval over this snapshot can support an answer"
                ),
                matched_rules=("after_snapshot_anchor",),
                companies=companies,
                metrics=metrics,
                future_reference=future,
            )

        # The mirror of the future check: a window that closes before collection
        # began is outside the snapshot's coverage, so no amount of retrieval
        # can support an answer about it either.
        if (
            self.coverage_start
            and window.basis == "absolute"
            and window.end <= self.coverage_start
        ):
            return RouteDecision(
                question=question,
                intent="unsupported",
                strategies=INTENT_STRATEGIES["unsupported"],
                time_window=window,
                confidence=1.0,
                method=f"{method}+snapshot_bound",
                rationale=(
                    f"the question asks about {window.label}, which ends before the collection "
                    f"window opens at {self.coverage_start}; the snapshot holds no evidence from "
                    "that period"
                ),
                matched_rules=("before_coverage_start",),
                companies=companies,
                metrics=metrics,
            )

        if method == "rules":
            intent, confidence, rules, rationale = classify_with_rules(question)
            scores: dict[str, float] = {}
        else:
            intent, confidence, scores = self.classifier.predict(question)
            rules = ()
            ranked = sorted(scores.items(), key=lambda item: -item[1])[:3]
            rationale = "TF-IDF logistic classifier: " + ", ".join(
                f"{label}={probability:.2f}" for label, probability in ranked
            )

        return RouteDecision(
            question=question,
            intent=intent,
            strategies=INTENT_STRATEGIES[intent],
            time_window=window,
            confidence=confidence,
            method=method,
            rationale=rationale,
            matched_rules=rules,
            scores=scores,
            companies=companies,
            metrics=metrics,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "methods_available": list(ROUTING_METHODS),
            "snapshot_anchor": self.snapshot_anchor,
            "intents": list(INTENTS),
            "intent_strategies": {key: list(value) for key, value in INTENT_STRATEGIES.items()},
            "rule_count": len(INTENT_RULES),
            "training_questions": len(TRAINING_QUESTIONS),
            "cohort_companies": len(self.company_ids),
        }


__all__ = [
    "EVIDENCE_STATE_TERMS",
    "INTENTS",
    "INTENT_RULES",
    "INTENT_STRATEGIES",
    "OPERATIONAL_TERMS",
    "ROUTING_METHODS",
    "TRAINING_QUESTIONS",
    "QueryRouter",
    "RouteDecision",
    "TfidfLogisticIntentClassifier",
    "classify_with_rules",
    "detect_companies",
    "detect_metrics",
    "tokenize",
]
