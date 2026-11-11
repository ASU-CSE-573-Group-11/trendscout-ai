"""LDA topic model and weekly topic trends — the proposal's lightweight baseline.

Proposal section 3 lists, under classical trend-discovery baselines, "LDA [2] as
a lightweight topic baseline; distinct-source counts and EWMA/rolling z-scores
after deduplication". The second half is :mod:`signals.news_features` and
:mod:`signals.ewma`; this module is the first half, and it produces weekly
series that the *same* scorer consumes, so "which topics are rising" is answered
by the machinery already in place rather than by a parallel code path.

Implementation
--------------
Latent Dirichlet Allocation (Blei, Ng and Jordan, 2003) fitted by collapsed
Gibbs sampling (Griffiths and Steyvers, 2004). Written in plain Python with no
scikit-learn or gensim, because CI installs only ``requirements.txt``. For a
corpus of this size — hundreds of short passages — a Gibbs sampler is fast
enough, and it avoids a heavy dependency for a baseline.

Sampling is seeded and every iteration order is deterministic, so a frozen
snapshot yields the same topics on every run. That matters more here than raw
speed: a baseline whose topics shift between runs cannot be compared against
anything.

Honest scope
------------
LDA needs a corpus to be meaningful. On a handful of documents it will still
return topics, and they will be noise. :meth:`TopicModel.describe` reports the
document count, vocabulary size, and whether the corpus cleared
``min_documents``; below that threshold the model is marked ``underpowered`` and
callers should say so rather than present the topics as findings.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from retrieval.passages import Passage, passages_from_records
from signals.series import WeekPoint, WeeklySeries
from signals.weeks import iso_week, parse_instant, parse_iso_week, week_range

SIGNAL_FAMILY = "topics"
TOPIC_METHOD = "lda_collapsed_gibbs_v1"

_WORD = re.compile(r"[a-z][a-z0-9+#.\-]{1,}")

#: Standard English function words. Removing them keeps topics about content.
STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are aren as at be because been before
    being below between both but by can cannot could couldn did didn do does doesn doing don down
    during each few for from further had hadn has hasn have haven having he her here hers herself
    him himself his how i if in into is isn it its itself just ll me more most mustn my myself no
    nor not now of off on once only or other our ours ourselves out over own re s same shan she
    should shouldn so some such t than that the their theirs them themselves then there these they
    this those through to too under until up ve very was wasn we were weren what when where which
    while who whom why will with won would wouldn you your yours yourself yourselves
    """.split()
)

#: Domain-generic words that appear in nearly every record and carry no topic.
#: Kept separate from the function words so a caller can switch it off and see
#: what difference it made.
DOMAIN_STOPWORDS: frozenset[str] = frozenset(
    """
    ai company companies said says new news today announced announcement startup startups
    inc llc team teams work working remote hiring hire role roles job jobs position
    skills engineer engineers http https www com
    """.split()
)


def tokenize(text: str, *, stopwords: frozenset[str], min_length: int = 3) -> list[str]:
    return [
        token
        for token in _WORD.findall((text or "").lower())
        if len(token) >= min_length and token not in stopwords and not token.isdigit()
    ]


@dataclass(frozen=True)
class TopicConfig:
    """Model size and sampler settings, reported with the model."""

    topics: int = 6
    alpha: float | None = None
    beta: float = 0.01
    iterations: int = 300
    burn_in: int = 50
    seed: int = 20261110
    min_document_frequency: int = 2
    max_document_ratio: float = 0.6
    min_documents: int = 25
    use_domain_stopwords: bool = True

    def __post_init__(self) -> None:
        if self.topics < 2:
            raise ValueError("topics must be at least 2")
        if self.iterations < 10:
            raise ValueError("iterations must be at least 10")
        if not 0 <= self.burn_in < self.iterations:
            raise ValueError("burn_in must be below iterations")
        if self.beta <= 0:
            raise ValueError("beta must be positive")
        if self.alpha is not None and self.alpha <= 0:
            raise ValueError("alpha must be positive")
        if not 0 < self.max_document_ratio <= 1:
            raise ValueError("max_document_ratio must be in (0, 1]")

    @property
    def effective_alpha(self) -> float:
        # A sparse document-topic prior. The textbook default of 50/K is tuned
        # for long documents; these passages are a few dozen tokens, and at
        # 50/K the prior swamps the observed counts, leaving every document an
        # almost uniform mixture and the dominant topic effectively arbitrary.
        return self.alpha if self.alpha is not None else 0.1

    def as_dict(self) -> dict[str, Any]:
        return {
            "topics": self.topics,
            "alpha": self.effective_alpha,
            "beta": self.beta,
            "iterations": self.iterations,
            "burn_in": self.burn_in,
            "seed": self.seed,
            "min_document_frequency": self.min_document_frequency,
            "max_document_ratio": self.max_document_ratio,
            "min_documents": self.min_documents,
            "method": TOPIC_METHOD,
        }


@dataclass
class Topic:
    """One fitted topic."""

    index: int
    terms: tuple[tuple[str, float], ...]
    weight: float

    @property
    def topic_id(self) -> str:
        return f"topic-{self.index:02d}"

    @property
    def label(self) -> str:
        """A readable label: the three strongest terms."""
        return ", ".join(term for term, _ in self.terms[:3]) or self.topic_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "index": self.index,
            "label": self.label,
            "weight": round(self.weight, 6),
            "terms": [{"term": term, "probability": round(value, 6)} for term, value in self.terms],
        }


@dataclass
class TopicModel:
    """A fitted LDA model over a passage corpus."""

    config: TopicConfig
    vocabulary: tuple[str, ...]
    topics: list[Topic]
    document_topics: dict[str, tuple[float, ...]]
    document_passages: dict[str, Passage]
    dropped_passages: tuple[str, ...] = ()
    log_likelihood: float | None = None

    @property
    def underpowered(self) -> bool:
        """True when the corpus is too small for the topics to mean anything."""
        return len(self.document_topics) < self.config.min_documents

    def topic(self, index: int) -> Topic:
        return self.topics[index]

    def dominant_topic(self, passage_id: str) -> int | None:
        weights = self.document_topics.get(passage_id)
        if not weights:
            return None
        best = max(range(len(weights)), key=lambda index: weights[index])
        return best

    def describe(self) -> dict[str, Any]:
        return {
            "method": TOPIC_METHOD,
            "config": self.config.as_dict(),
            "documents": len(self.document_topics),
            "dropped_documents": len(self.dropped_passages),
            "vocabulary": len(self.vocabulary),
            "topics": [topic.as_dict() for topic in self.topics],
            "log_likelihood": self.log_likelihood,
            "underpowered": self.underpowered,
            "caveat": (
                f"fitted on {len(self.document_topics)} documents, below the "
                f"{self.config.min_documents}-document minimum; treat the topics as a smoke "
                "test rather than a finding"
                if self.underpowered
                else None
            ),
        }


def _build_vocabulary(
    tokenized: Sequence[Sequence[str]], config: TopicConfig
) -> tuple[tuple[str, ...], dict[str, int], str | None]:
    document_frequency: dict[str, int] = {}
    for tokens in tokenized:
        for term in set(tokens):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    total = len(tokenized)
    note: str | None = None
    maximum = max(1, int(config.max_document_ratio * total))

    def select(minimum: int) -> list[str]:
        return sorted(
            term
            for term, count in document_frequency.items()
            if count >= minimum and count <= maximum
        )

    vocabulary = select(config.min_document_frequency)
    if not vocabulary and config.min_document_frequency > 1:
        # A small corpus can leave nothing above the frequency floor. Falling
        # back is better than fitting on an empty vocabulary, but it is a
        # thinner model and the caller is told.
        vocabulary = select(1)
        note = (
            f"no term met min_document_frequency={config.min_document_frequency}; "
            "fell back to 1, so the vocabulary includes terms seen in a single document"
        )
    return tuple(vocabulary), {term: index for index, term in enumerate(vocabulary)}, note


def fit_topics(
    passages: Iterable[Passage] | Iterable[Mapping[str, Any]],
    *,
    config: TopicConfig | None = None,
    source_types: Sequence[str] | None = ("news", "company", "public_voice", "funding"),
) -> TopicModel:
    """Fit LDA over passages by collapsed Gibbs sampling.

    Records are accepted directly and converted to passages, so callers can
    pass a snapshot without preparing it.
    """
    config = config or TopicConfig()
    items = list(passages)
    if items and not isinstance(items[0], Passage):
        items = passages_from_records(items, source_types=source_types)  # type: ignore[arg-type]
    corpus: list[Passage] = list(items)  # type: ignore[assignment]

    stopwords = STOPWORDS | (DOMAIN_STOPWORDS if config.use_domain_stopwords else frozenset())
    tokenized = [tokenize(passage.search_text, stopwords=stopwords) for passage in corpus]
    vocabulary, term_index, _note = _build_vocabulary(tokenized, config)

    documents: list[list[int]] = []
    kept: list[Passage] = []
    dropped: list[str] = []
    for passage, tokens in zip(corpus, tokenized):
        ids = [term_index[token] for token in tokens if token in term_index]
        if ids:
            documents.append(ids)
            kept.append(passage)
        else:
            dropped.append(passage.passage_id)

    vocabulary_size = len(vocabulary)
    topics_count = config.topics
    alpha, beta = config.effective_alpha, config.beta

    if not documents or vocabulary_size == 0:
        return TopicModel(
            config=config,
            vocabulary=vocabulary,
            topics=[Topic(index=index, terms=(), weight=0.0) for index in range(topics_count)],
            document_topics={},
            document_passages={},
            dropped_passages=tuple(dropped),
        )

    rng = random.Random(config.seed)
    assignments: list[list[int]] = [
        [rng.randrange(topics_count) for _ in document] for document in documents
    ]
    document_topic = [[0] * topics_count for _ in documents]
    topic_term = [[0] * vocabulary_size for _ in range(topics_count)]
    topic_total = [0] * topics_count

    for document_index, document in enumerate(documents):
        for position, term in enumerate(document):
            topic = assignments[document_index][position]
            document_topic[document_index][topic] += 1
            topic_term[topic][term] += 1
            topic_total[topic] += 1

    beta_sum = vocabulary_size * beta
    accumulated = [[0.0] * topics_count for _ in documents]
    samples_taken = 0

    for iteration in range(config.iterations):
        for document_index, document in enumerate(documents):
            counts = document_topic[document_index]
            for position, term in enumerate(document):
                topic = assignments[document_index][position]
                counts[topic] -= 1
                topic_term[topic][term] -= 1
                topic_total[topic] -= 1

                weights = [
                    (counts[candidate] + alpha)
                    * (topic_term[candidate][term] + beta)
                    / (topic_total[candidate] + beta_sum)
                    for candidate in range(topics_count)
                ]
                total = sum(weights)
                threshold = rng.random() * total
                cumulative = 0.0
                chosen = topics_count - 1
                for candidate, weight in enumerate(weights):
                    cumulative += weight
                    if cumulative >= threshold:
                        chosen = candidate
                        break

                assignments[document_index][position] = chosen
                counts[chosen] += 1
                topic_term[chosen][term] += 1
                topic_total[chosen] += 1

        if iteration >= config.burn_in:
            # Average the post-burn-in document-topic counts rather than taking
            # the final sweep, which is one draw from a noisy chain.
            samples_taken += 1
            for document_index, document in enumerate(documents):
                length = len(document)
                counts = document_topic[document_index]
                for topic in range(topics_count):
                    accumulated[document_index][topic] += (counts[topic] + alpha) / (
                        length + topics_count * alpha
                    )

    divisor = samples_taken or 1
    document_topics = {
        kept[index].passage_id: tuple(value / divisor for value in accumulated[index])
        for index in range(len(kept))
    }

    topics: list[Topic] = []
    corpus_length = sum(topic_total) or 1
    for topic in range(topics_count):
        probabilities = [
            (topic_term[topic][term] + beta) / (topic_total[topic] + beta_sum)
            for term in range(vocabulary_size)
        ]
        order = sorted(
            range(vocabulary_size), key=lambda term: (-probabilities[term], vocabulary[term])
        )[:12]
        topics.append(
            Topic(
                index=topic,
                terms=tuple((vocabulary[term], probabilities[term]) for term in order),
                weight=topic_total[topic] / corpus_length,
            )
        )

    log_likelihood = 0.0
    for document_index, document in enumerate(documents):
        theta = document_topics[kept[document_index].passage_id]
        for term in document:
            probability = sum(
                theta[topic]
                * (topic_term[topic][term] + beta)
                / (topic_total[topic] + beta_sum)
                for topic in range(topics_count)
            )
            log_likelihood += math.log(probability) if probability > 0 else 0.0

    return TopicModel(
        config=config,
        vocabulary=vocabulary,
        topics=topics,
        document_topics=document_topics,
        document_passages={passage.passage_id: passage for passage in kept},
        dropped_passages=tuple(dropped),
        log_likelihood=log_likelihood,
    )


def topic_weekly_series(
    model: TopicModel,
    *,
    coverage_start: str | None = None,
    coverage_end: str | None = None,
    minimum_weight: float = 0.0,
) -> list[WeeklySeries]:
    """Weekly distinct-origin counts per topic, ready for the EWMA scorer.

    Origins are counted rather than documents, for the same reason
    :mod:`signals.news_features` does: syndicated copies of one origin are one
    piece of attention, not several. Weeks inside the coverage span with no
    document are real zeros, because the feeds behind these passages are
    harvested continuously.
    """
    by_topic_week: dict[tuple[int, str], dict[str, Passage]] = {}
    weeks: set[str] = set()

    for passage_id, weights in model.document_topics.items():
        passage = model.document_passages[passage_id]
        timestamp = passage.best_time
        if not timestamp:
            continue
        label = iso_week(parse_instant(timestamp))
        weeks.add(label)
        topic = max(range(len(weights)), key=lambda index: weights[index])
        if weights[topic] < minimum_weight:
            continue
        by_topic_week.setdefault((topic, label), {})[passage.origin_cluster_id] = passage

    if not weeks:
        return []
    start = coverage_start or min(weeks, key=parse_iso_week)
    end = coverage_end or max(weeks, key=parse_iso_week)
    span = week_range(start, end)

    series: list[WeeklySeries] = []
    for topic in model.topics:
        observations: dict[str, WeekPoint] = {}
        for label in span:
            members = by_topic_week.get((topic.index, label))
            if not members:
                continue
            observations[label] = WeekPoint(
                iso_week=label,
                value=float(len(members)),
                value_state="observed",
                record_ids=tuple(sorted(passage.record_id for passage in members.values())),
                origin_cluster_ids=tuple(sorted(members)),
                notes=(f"independent origins whose dominant topic is {topic.topic_id}",),
            )
        series.append(
            WeeklySeries.from_observations(
                series_id=f"{SIGNAL_FAMILY}:topic_origins|topic={topic.topic_id}",
                metric="topic_origins",
                signal_family=SIGNAL_FAMILY,
                entity_type="topic",
                entity_id=topic.topic_id,
                company_id=None,
                observations=observations,
                gap_policy="zero",
                coverage_start=start,
                coverage_end=end,
                metadata={
                    "topic_label": topic.label,
                    "topic_terms": [term for term, _ in topic.terms[:8]],
                    "topic_weight": round(topic.weight, 6),
                    "method": TOPIC_METHOD,
                    "underpowered": model.underpowered,
                },
            )
        )
    return series


def company_topic_series(model: TopicModel) -> list[WeeklySeries]:
    """Weekly distinct-origin counts per company and topic.

    Lets the baseline answer "which topics is this company gaining attention
    for", alongside the corpus-wide view.
    """
    grouped: dict[tuple[str, int, str], dict[str, Passage]] = {}
    weeks: set[str] = set()
    for passage_id, weights in model.document_topics.items():
        passage = model.document_passages[passage_id]
        if not passage.company_id or not passage.best_time:
            continue
        label = iso_week(parse_instant(passage.best_time))
        weeks.add(label)
        topic = max(range(len(weights)), key=lambda index: weights[index])
        grouped.setdefault((passage.company_id, topic, label), {})[
            passage.origin_cluster_id
        ] = passage

    if not weeks:
        return []
    span = week_range(min(weeks, key=parse_iso_week), max(weeks, key=parse_iso_week))

    series: list[WeeklySeries] = []
    pairs = sorted({(company_id, topic) for company_id, topic, _ in grouped})
    for company_id, topic in pairs:
        label_text = model.topic(topic).label
        observations = {
            label: WeekPoint(
                iso_week=label,
                value=float(len(members)),
                value_state="observed",
                record_ids=tuple(sorted(item.record_id for item in members.values())),
                origin_cluster_ids=tuple(sorted(members)),
            )
            for label in span
            if (members := grouped.get((company_id, topic, label)))
        }
        series.append(
            WeeklySeries.from_observations(
                series_id=(
                    f"{SIGNAL_FAMILY}:topic_origins|company={company_id}"
                    f"|topic=topic-{topic:02d}"
                ),
                metric="topic_origins",
                signal_family=SIGNAL_FAMILY,
                entity_type="company_topic",
                entity_id=f"{company_id}:topic-{topic:02d}",
                company_id=company_id,
                observations=observations,
                gap_policy="zero",
                coverage_start=span[0],
                coverage_end=span[-1],
                metadata={"topic_label": label_text, "method": TOPIC_METHOD},
            )
        )
    return series


__all__ = [
    "DOMAIN_STOPWORDS",
    "SIGNAL_FAMILY",
    "STOPWORDS",
    "TOPIC_METHOD",
    "Topic",
    "TopicConfig",
    "TopicModel",
    "company_topic_series",
    "fit_topics",
    "tokenize",
    "topic_weekly_series",
]
