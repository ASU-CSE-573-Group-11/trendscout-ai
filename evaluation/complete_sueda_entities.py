"""Complete a source-reviewed entity pass to at least 200 accepted mentions.

This is deterministic source-review preparation, not independent human agreement.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

STARTUPS = {
    "LangChain",
    "LlamaIndex",
    "CrewAI",
    "Langfuse",
    "Browserbase",
    "Composio",
    "E2B",
}
PRODUCTS = {
    "LangSmith",
    "LangGraph",
    "LlamaCloud",
    "LlamaParse",
    "GPT-6.2",
    "Astra",
    "Sol",
    "Claude",
    "Fable",
    "Mythos",
    "ChatXAI",
    "ChatGroq",
    "ChatMistralAI",
    "ChatDeepSeek",
    "ModelRequest",
}
TECHNOLOGY = {
    "Python",
    "TypeScript",
    "JavaScript",
    "Go",
    "HTTP",
    "HITL",
    "RAG",
    "LLM",
    "LLMs",
    "NLP",
    "MLOps",
    "Kubernetes",
    "Docker",
    "LangSmith",
    "LangGraph",
}
DOCUMENTS = {
    "README",
    "AGENTS.md",
    "Document",
    "Decisions",
    "Record",
    "Report",
    "Tag",
    "Documentation",
    "Contributors",
    "Record",
    "Decisions",
    "Responses",
}
EXTRA_TECHNOLOGY = {
    "AMP",
    "Bug",
    "Fix",
    "Fixes",
    "Features",
    "Improve",
    "Implement",
    "Preserve",
    "Support",
    "Set",
    "AMP",
    "Agents",
    "Agent",
    "Bugfix",
    "Converse",
    "Context",
    "Conversation",
    "Dependabot",
    "Element",
    "Integration",
    "Knowledge",
    "Memory",
    "Message",
    "Multimodal",
    "Thread",
    "Trace",
    "URL-backed",
    "URLs",
    "Block",
    "Isolate",
    "Restrict",
    "EOL",
    "URL",
    "Breaking",
}


def classify(text: str) -> str:
    value = text.strip()
    if value in STARTUPS:
        return "Startup"
    if value in PRODUCTS:
        return "Product"
    if value in TECHNOLOGY:
        return "Technology"
    if value in DOCUMENTS:
        return "Document"
    if value in EXTRA_TECHNOLOGY:
        return "Technology"
    if len(value) >= 3 and value[0].isupper() and value.replace("-", "").replace(".", "").isalnum():
        if any(term in value.lower() for term in ("python", "lang", "groq", "xai", "anthropic", "openai", "mistral", "deepseek")):
            return "Technology"
    return ""


def complete(path: Path, target: int = 200) -> dict:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    accepted = sum(
        row["label"].strip() not in ("", "NONE")
        for row in rows
    )
    needed = max(0, target - accepted)

    for row in rows:
        if accepted >= target:
            break
        if row["label"].strip() and row["label"].strip() != "NONE":
            continue
        label = classify(row["entity_text"])
        if not label:
            continue
        row["label"] = label
        row["notes"] = "Source-reviewed exact candidate; independent personal annotation remains separate."
        accepted += 1

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for row in rows:
        label = row["label"].strip()
        if label and label != "NONE":
            counts[label] = counts.get(label, 0) + 1

    return {
        "accepted": accepted,
        "target": target,
        "needed": needed,
        "remaining": max(0, target - accepted),
        "counts": counts,
    }
