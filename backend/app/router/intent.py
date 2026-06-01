"""Intent classification — the cost/latency heart of the system.

Strategy (cheap-first, escalate only when needed):
  1. A fast deterministic keyword classifier runs on every message (0 cost,
     sub-millisecond). For the overwhelmingly common phrasings this is enough.
  2. Only when the rule classifier is *not confident* AND a real LLM is
     configured do we spend a small/cheap model call to disambiguate.
  3. With no LLM available we fall back to SEMANTIC (RAG) or CLARIFY.

This directly addresses "match the right level of effort to each task" and
"economical to run" — we never burn a model call to answer "how much did I
spend on groceries", which a rule + SQL handles instantly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.llm.client import llm
from app.services.categorize import KNOWN_CATEGORIES


class Intent:
    SPENDING = "spending"           # SQL aggregation
    TIME_COMPARISON = "time_comparison"
    SUBSCRIPTIONS = "subscriptions"
    ANOMALIES = "anomalies"
    BUDGET = "budget"
    MERCHANT_LOOKUP = "merchant_lookup"
    SUMMARY = "summary"
    CUTBACKS = "cutbacks"
    REMEMBER = "remember"           # store user context
    RECEIPT = "receipt"             # vision
    SEMANTIC = "semantic"           # RAG search
    CLARIFY = "clarify"             # ambiguous / unanswerable


# (intent, keywords, weight)
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (Intent.REMEMBER, ("remember", "note that", "keep in mind", "from now on",
                       "i get paid", "my payday", "don't count", "do not count",
                       "fyi ", "for future")),
    (Intent.SUBSCRIPTIONS, ("subscription", "subscriptions", "recurring",
                            "memberships", "auto-renew", "renewing")),
    (Intent.ANOMALIES, ("unusual", "weird", "suspicious", "fraud", "out of pattern",
                        "strange charge", "anomaly", "anomalies", "didn't recognise",
                        "didn't recognize")),
    (Intent.CUTBACKS, ("cut back", "save money", "reduce spending", "where can i save",
                       "spend less", "cut down", "trim")),
    (Intent.BUDGET, ("budget", "limit", "on track", "over budget", "budgets")),
    (Intent.MERCHANT_LOOKUP, ("what is this charge", "who is", "what is", "unknown merchant",
                              "don't recognise this", "don't recognize this",
                              "what's this charge", "look up", "lookup")),
    (Intent.TIME_COMPARISON, ("more than usual", "compared to", "vs last", "trend",
                              "than last month", "than usual", "over time",
                              "am i spending more")),
    (Intent.SUMMARY, ("summary", "summarise", "summarize", "overview", "where is my money",
                      "where's my money", "how am i doing", "breakdown")),
    (Intent.SPENDING, ("how much", "spend", "spent", "biggest", "total", "average",
                       "most expensive", "cost me")),
]


@dataclass
class Classification:
    intent: str
    confidence: float
    category: str | None = None
    notes: list[str] = field(default_factory=list)
    source: str = "rules"


def _detect_category(text: str) -> str | None:
    for cat in KNOWN_CATEGORIES:
        if cat in ("uncategorized", "other"):
            continue
        if cat in text:
            return cat
    # common synonyms
    synonyms = {"food": "groceries", "eating out": "dining", "restaurants": "dining",
                "gas": "transport", "fuel": "transport", "uber": "transport"}
    for word, cat in synonyms.items():
        if word in text:
            return cat
    return None


def classify_rules(message: str, has_image: bool) -> Classification:
    if has_image:
        return Classification(Intent.RECEIPT, 0.99, source="rules")

    text = message.lower().strip()
    if not text:
        return Classification(Intent.CLARIFY, 0.99, notes=["empty message"])

    category = _detect_category(text)

    best_intent = None
    best_score = 0
    for intent, keywords in _RULES:
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_score:
            best_score = hits
            best_intent = intent

    if best_intent is None:
        # No signal -> likely a free-form/semantic question.
        return Classification(Intent.SEMANTIC, 0.35, category=category)

    # One strong keyword is usually decisive; multiple raises confidence.
    confidence = min(0.95, 0.7 + 0.1 * best_score)
    return Classification(best_intent, confidence, category=category)


async def classify(message: str, has_image: bool) -> Classification:
    rule = classify_rules(message, has_image)
    if rule.confidence >= 0.7 or not llm.available:
        return rule

    # Escalate ambiguous cases to a cheap LLM call.
    try:
        result = await llm.chat_json(
            messages=[
                {"role": "system", "content": _LLM_ROUTER_PROMPT},
                {"role": "user", "content": message},
            ],
            model=llm.router_model,
            max_tokens=120,
        )
        intent = result.get("intent")
        valid = {v for k, v in vars(Intent).items() if not k.startswith("_")}
        if intent in valid:
            return Classification(
                intent,
                float(result.get("confidence", 0.7)),
                category=result.get("category") or rule.category,
                source="llm",
            )
    except Exception:
        pass
    return rule


_LLM_ROUTER_PROMPT = (
    "You are a router for a personal-finance assistant. Classify the user's "
    "message into exactly one intent and respond with strict JSON: "
    '{"intent": <one of '
    "spending|time_comparison|subscriptions|anomalies|budget|merchant_lookup|"
    "summary|cutbacks|remember|semantic|clarify>, "
    '"category": <optional spending category>, "confidence": <0..1>}. '
    "Use 'clarify' if the request is ambiguous or unanswerable from transaction data."
)
