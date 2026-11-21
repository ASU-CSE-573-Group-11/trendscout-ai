"""Answer providers: extractive by default, LLM-backed when configured.

Every provider receives the **same** evidence bundle and is required to produce
the same thing: numbered claims, each citing the evidence that supports it. The
interface then assigns evidence states to those claims. A provider never sees
the full snapshot, only the passages, graph rows, and trend signals that
retrieval selected for this question and time window.

``ExtractiveProvider`` is the default. It composes an answer from the selected
evidence without generating new prose, so it cannot introduce an unsupported
claim and it needs no API key. That makes it the honest baseline and the
fallback whenever a configured provider is unavailable.

``AnthropicProvider`` calls the Claude Messages API. It is given a system prompt
that forbids any claim the evidence does not support, requires a citation marker
on every sentence, and requires an explicit statement of insufficiency instead
of a guess. Sentences it returns without a citation marker are counted and
reported as unsupported rather than quietly accepted, which is what makes the
proposal's unsupported-claim rate measurable.

Provider selection is configuration, not code: ``build_provider("extractive")``,
``build_provider("anthropic")``, or ``build_provider("anthropic:claude-sonnet-5-5")``.
With no API key present the Anthropic provider reports itself unavailable and
the caller falls back to extractive, with the reason recorded in the answer.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"

# Plain sentence splitting, for text that carries no citation markers yet.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_CITATION = re.compile(r"\[(\d+)\]")
# A claim ends at terminal punctuation together with any citation markers that
# follow it: "…agent infrastructure. [1] Hiring also grew. [4]" is two cited
# claims. Splitting before the markers would leave each claim uncited, and not
# splitting at all would merge two claims into one.
_CLAIM_END = re.compile(r"[.!?](?:\s*\[\d+\])*")

SYSTEM_PROMPT = """You answer questions about AI startups strictly from the evidence given to you.

Rules, in order of priority:
1. Use only the numbered evidence provided. Do not add facts from your own knowledge, \
including facts you are confident about.
2. End every sentence that states a fact with the citation markers for the evidence \
supporting it, like [1] or [2][5]. A sentence with no marker will be rejected as unsupported.
3. If the evidence does not answer the question, say so plainly and name what is missing. \
Do not guess, and do not fill a gap with a plausible-sounding statement.
4. Never state or imply a prediction about the future. The evidence describes what was \
observed in a past time window.
5. If independent sources disagree, report the disagreement and cite both. Do not pick one.
6. Keep the answer under 120 words. Facts, not framing."""


@dataclass
class ProviderResult:
    """What a provider returns."""

    text: str
    provider: str
    model: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    refused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "usage": dict(self.usage),
            "refused": self.refused,
        }


class AnswerProvider(Protocol):
    """Turn an evidence bundle into cited prose."""

    name: str

    def available(self) -> tuple[bool, str | None]:
        """``(usable, reason it is not)``."""

    def generate(self, question: str, evidence: Sequence[Mapping[str, Any]], *, context: Mapping[str, Any]) -> ProviderResult:
        ...


def format_evidence_block(evidence: Sequence[Mapping[str, Any]]) -> str:
    """Render the numbered evidence a provider is allowed to use."""
    lines: list[str] = []
    for item in evidence:
        number = item["number"]
        kind = item.get("kind", "passage")
        when = item.get("when") or "no date recorded"
        header = f"[{number}] ({kind}, {when})"
        title = item.get("title")
        if title:
            header += f" {title}"
        lines.append(header)
        text = (item.get("text") or "").strip()
        if text:
            lines.append(f"    {text}")
        lines.append("")
    return "\n".join(lines).strip()


def format_context_block(context: Mapping[str, Any]) -> str:
    parts = [
        f"Snapshot date: {context.get('snapshot_anchor')}",
        f"Time window used: {context.get('time_window_label')} "
        f"({context.get('time_window_start')} to {context.get('time_window_end')})",
        f"Question intent: {context.get('intent')}",
    ]
    if context.get("graph_summary"):
        parts.append(f"Graph results: {context['graph_summary']}")
    if context.get("trend_summary"):
        parts.append(f"Trend signals: {context['trend_summary']}")
    findings = context.get("findings") or ()
    if findings:
        parts.append(
            "Computed findings (already derived from the evidence; cite the markers shown):"
        )
        for finding in findings:
            markers = "".join(f"[{number}]" for number in finding.get("citation_numbers", ()))
            parts.append(f"  - {finding['text']} {markers}".rstrip())
    return "\n".join(parts)


@dataclass
class ExtractiveProvider:
    """Compose an answer from the selected evidence, generating no new prose.

    The output is assembled from the evidence's own text, each fragment carrying
    the citation of the item it came from, so there is nothing in the answer
    that is not in the evidence.
    """

    max_items: int = 4
    max_sentence_chars: int = 320
    name: str = "extractive"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def generate(
        self, question: str, evidence: Sequence[Mapping[str, Any]], *, context: Mapping[str, Any]
    ) -> ProviderResult:
        if not evidence:
            return ProviderResult(
                text=(
                    "The snapshot does not contain evidence that answers this question. "
                    "No supporting record was retrieved for the requested time window."
                ),
                provider=self.name,
            )

        lines: list[str] = []
        window = context.get("time_window_label") or "the full snapshot"
        lines.append(f"For {window}, from {len(evidence)} retrieved item(s):")

        # Findings answer the question directly and are computed from the graph
        # and trend signals, so they lead. The passage excerpts that follow are
        # supporting detail, not the answer.
        findings: Sequence[Mapping[str, Any]] = context.get("findings") or ()
        for finding in findings:
            markers = "".join(f"[{number}]" for number in finding.get("citation_numbers", ()))
            lines.append(f"- {cite_every_sentence(finding['text'], markers)}".rstrip())

        remaining = max(0, self.max_items - len(findings))
        for item in list(evidence)[:remaining]:
            fragment = _leading_sentence(item.get("text") or item.get("title") or "", self.max_sentence_chars)
            if not fragment:
                continue
            lines.append(f"- {fragment} [{item['number']}]")
        return ProviderResult(text="\n".join(lines), provider=self.name)


def cite_every_sentence(text: str, markers: str) -> str:
    """Attach ``markers`` to every sentence of ``text``.

    A finding may run to two sentences ("…is emerging. What would change it:
    …"). Marking only the last one would leave the first counted as an
    unsupported claim, because claims are split per sentence.
    """
    if not markers:
        return text
    sentences = [piece.strip() for piece in _SENTENCE.split(text) if piece.strip()]
    if len(sentences) <= 1:
        return f"{text} {markers}".strip()
    return " ".join(f"{sentence} {markers}" for sentence in sentences)


def _leading_sentence(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    sentences = _SENTENCE.split(text)
    fragment = sentences[0] if sentences else text
    if len(fragment) > limit:
        fragment = fragment[: limit - 1].rstrip() + "…"
    return fragment


@dataclass
class AnthropicProvider:
    """Generate the answer with Claude, over the selected evidence only."""

    model: str = DEFAULT_ANTHROPIC_MODEL
    max_tokens: int = 1024
    effort: str = "low"
    api_key_env: str = "ANTHROPIC_API_KEY"
    name: str = "anthropic"

    def available(self) -> tuple[bool, str | None]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "the anthropic package is not installed"
        if not os.environ.get(self.api_key_env):
            return False, f"{self.api_key_env} is not set"
        return True, None

    def generate(  # pragma: no cover - requires a key and network
        self, question: str, evidence: Sequence[Mapping[str, Any]], *, context: Mapping[str, Any]
    ) -> ProviderResult:
        usable, reason = self.available()
        if not usable:
            raise RuntimeError(f"anthropic provider unavailable: {reason}")
        import anthropic

        client = anthropic.Anthropic()
        prompt = (
            f"{format_context_block(context)}\n\n"
            f"Evidence:\n{format_evidence_block(evidence)}\n\n"
            f"Question: {question}"
        )
        try:
            # Effort is kept low by default: the proposal targets a median
            # response under eight seconds, and this is a grounded-extraction
            # task rather than a reasoning-heavy one.
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"anthropic request failed with {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"anthropic request could not reach the API: {exc}") from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            return ProviderResult(
                text="The answer provider declined to generate a response for this question.",
                provider=self.name,
                model=self.model,
                refused=True,
                fallback_reason=getattr(details, "explanation", None) or "provider refusal",
            )

        text = "\n".join(block.text for block in response.content if block.type == "text").strip()
        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
        }
        return ProviderResult(text=text, provider=self.name, model=self.model, usage=usage)


def build_provider(spec: str | None = None, **kwargs: Any) -> AnswerProvider:
    """Resolve a provider from a config string.

    ``None`` or ``"extractive"`` gives the dependency-free default;
    ``"anthropic"`` or ``"anthropic:<model>"`` gives the Claude provider.
    """
    if not spec or spec == "extractive":
        return ExtractiveProvider(**kwargs)
    if spec.startswith("anthropic"):
        _, _, model = spec.partition(":")
        return AnthropicProvider(model=model or DEFAULT_ANTHROPIC_MODEL, **kwargs)
    raise ValueError(
        f"unsupported provider {spec!r}; use 'extractive' or 'anthropic[:model]'"
    )


def _split_sentences_with_citations(line: str) -> list[str]:
    """Split one line into sentences, keeping each sentence's citations with it.

    A boundary is terminal punctuation plus any citation markers that follow,
    and only when whitespace or the end of the line comes next. That condition
    is what stops a decimal ("score 2.49), commits…") from being read as a
    sentence end.
    """
    pieces: list[str] = []
    start = 0
    for match in _CLAIM_END.finditer(line):
        end = match.end()
        rest = line[end:]
        if rest and not rest[:1].isspace():
            continue
        piece = line[start:end].strip()
        if piece:
            pieces.append(piece)
        start = end
    tail = line[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces or [line]


def split_claims(text: str) -> list[tuple[str, tuple[int, ...]]]:
    """Split generated text into claims and the citation numbers each carries.

    A line or sentence with no citation marker returns an empty tuple, which the
    interface records as an unsupported claim rather than discarding.
    """
    claims: list[tuple[str, tuple[int, ...]]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().lstrip("-•*").strip()
        if not line:
            continue
        for piece in _split_sentences_with_citations(line):
            piece = piece.strip()
            if not piece:
                continue
            numbers = tuple(sorted({int(value) for value in _CITATION.findall(piece)}))
            cleaned = _CITATION.sub("", piece).strip()
            cleaned = re.sub(r"\s{2,}", " ", cleaned)
            if cleaned.endswith(":") and not numbers:
                # A lead-in such as "Based on 3 retrieved items:" states no fact.
                continue
            claims.append((cleaned, numbers))
    return claims


__all__ = [
    "DEFAULT_ANTHROPIC_MODEL",
    "SYSTEM_PROMPT",
    "AnswerProvider",
    "AnthropicProvider",
    "ExtractiveProvider",
    "ProviderResult",
    "build_provider",
    "cite_every_sentence",
    "format_context_block",
    "format_evidence_block",
    "split_claims",
]
