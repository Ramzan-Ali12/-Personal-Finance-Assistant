"""Agent handler — multi-step / tool-using reasoning.

Covers the capabilities that are *not* a single aggregation: subscriptions,
anomalies, budgets, cut-backs, and unknown-merchant lookup. The merchant
lookup is genuinely agentic: it gathers context from the DB, optionally calls
an external web-search tool, decides whether it has enough, and recovers
gracefully when a step is unavailable or fails.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.handlers.base import HandlerResult
from app.llm.client import llm
from app.models import Transaction
from app.router.intent import Classification
from app.router.narrate import narrate
from app.tools import anomalies as anomalies_tool
from app.tools import budgets as budgets_tool
from app.tools import cutbacks as cutbacks_tool
from app.tools import subscriptions as subs_tool
from app.tools.web_search import search_merchant


async def handle_subscriptions(session, user_id, message, cls, ctx_prefix):
    subs = await subs_tool.detect_subscriptions(session, user_id)
    used = ["agent.subscriptions"]
    if not subs:
        fallback = "I couldn't find any clearly recurring subscriptions yet."
    else:
        total = sum(s["est_monthly_cost"] for s in subs)
        lines = [f"{s['merchant']}: ${s['avg_amount']:.2f}/{s['cadence']}" for s in subs[:8]]
        fallback = (f"I found {len(subs)} recurring charges totalling about "
                    f"${total:.0f}/month:\n- " + "\n- ".join(lines))
    facts = {"subscriptions": subs}
    return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                         "agent", facts, used)


async def handle_anomalies(session, user_id, message, cls, ctx_prefix):
    found = await anomalies_tool.detect_anomalies(session, user_id)
    used = ["agent.anomalies"]
    if not found:
        fallback = "Nothing looks unusual in your recent activity."
    else:
        lines = [f"${a['amount']:.0f} at {a['merchant']} ({a['date']}): {a['reason']}"
                 for a in found[:6]]
        fallback = "Here are charges that stand out:\n- " + "\n- ".join(lines)
    facts = {"anomalies": found}
    return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                         "agent", facts, used)


async def handle_budget(session, user_id, message, cls, ctx_prefix):
    statuses = await budgets_tool.budget_status(session, user_id)
    used = ["agent.budget"]
    if not statuses:
        fallback = ("You haven't set any budgets yet. Set one and I'll track it "
                    "and warn you as you approach the limit.")
    else:
        lines = []
        for s in statuses:
            flag = {"ok": "on track", "warning": "close to limit", "over": "OVER budget"}[s["status"]]
            lines.append(f"{s['category']}: ${s['spent']:.0f}/${s['limit']:.0f} "
                         f"({s['pct_used']:.0f}%, {flag})")
        fallback = "Budget status:\n- " + "\n- ".join(lines)
    facts = {"budgets": statuses}
    return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                         "agent", facts, used)


async def handle_cutbacks(session, user_id, message, cls, ctx_prefix):
    suggestions = await cutbacks_tool.suggest_cutbacks(session, user_id)
    used = ["agent.cutbacks"]
    if not suggestions:
        fallback = "Your spending looks in line with your norms — no obvious cut-backs."
    else:
        total = sum(s["potential_savings"] for s in suggestions)
        lines = [s["suggestion"] for s in suggestions[:5]]
        fallback = (f"Here are ways to save ~${total:.0f}:\n- " + "\n- ".join(lines))
    facts = {"suggestions": suggestions}
    return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                         "agent", facts, used)


_STOPWORDS = {"what", "is", "the", "this", "charge", "who", "a", "an", "my", "from",
              "for", "on", "of", "merchant", "do", "you", "know", "about", "look",
              "up", "lookup", "recognise", "recognize", "i", "dont", "don't"}


def _extract_merchant_query(message: str) -> str | None:
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", message)
    if quoted:
        return quoted[0].strip()
    # Token that looks like a merchant code (caps/digits/asterisks).
    codes = re.findall(r"[A-Z0-9][A-Z0-9*#\-]{3,}", message)
    if codes:
        return codes[0]
    tokens = [w for w in re.findall(r"[A-Za-z0-9&]+", message)
              if w.lower() not in _STOPWORDS]
    return " ".join(tokens[-3:]) if tokens else None


async def handle_merchant_lookup(session, user_id, message, cls, ctx_prefix):
    """Multi-step: locate the charge -> research it -> explain (with recovery)."""
    used = ["agent.merchant_lookup"]
    notes: list[str] = []
    query = _extract_merchant_query(message)

    # Step 1: try to ground the question in an actual transaction.
    matched = None
    if query:
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.merchant.ilike(f"%{query}%"),
            )
            .order_by(Transaction.txn_date.desc())
            .limit(1)
        )
        matched = (await session.execute(stmt)).scalars().first()
    if matched is None:
        # Fallback: the most recent uncategorised charge is the likely target.
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id,
                   Transaction.category == "uncategorized",
                   Transaction.amount < 0)
            .order_by(Transaction.txn_date.desc())
            .limit(1)
        )
        matched = (await session.execute(stmt)).scalars().first()
        if matched:
            notes.append("Assumed you meant your most recent unrecognised charge.")
            query = matched.merchant

    target_desc = None
    if matched:
        target_desc = {
            "merchant": matched.merchant,
            "amount": round(-matched.amount, 2),
            "date": matched.txn_date.isoformat(),
        }

    # Step 2: research the merchant on the web (if a provider is configured).
    web = await search_merchant(query or message)
    if web.available:
        used.append("web_search")

    # Step 3: decide what we can confidently say & narrate.
    facts = {"target_charge": target_desc, "query": query,
             "web_search": web.as_dict()}

    if web.available and web.summary:
        fallback = (f"'{query}' appears to be: {web.summary}"
                    + (f" This matches your ${target_desc['amount']:.2f} charge on "
                       f"{target_desc['date']}." if target_desc else ""))
    elif llm.available:
        # No external search -> best-effort LLM guess, clearly labelled.
        notes.append("No web-search provider configured; this is a best guess.")
        guess = await narrate(
            f"What is the merchant/charge '{query}'? Give a likely identification.",
            facts,
            fallback=f"I couldn't look up '{query}' online.",
            context_prefix=ctx_prefix,
        )
        fallback = guess
    else:
        fallback = (
            f"I found the charge"
            + (f" (${target_desc['amount']:.2f} at {target_desc['merchant']} on "
               f"{target_desc['date']})" if target_desc else "")
            + ", but online lookup isn't configured, so I can't identify the "
              "merchant beyond what's in your data."
        )

    answer = await narrate(message, facts, fallback, ctx_prefix)
    return HandlerResult(answer, "agent", facts, used, notes)
