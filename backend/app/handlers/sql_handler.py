"""SQL handler — deterministic, instant answers for quantitative questions.

No LLM is required to get the *answer*; the model (if present) only phrases it.
All figures come from indexed aggregate queries, so this path is fast and
scales to arbitrarily large histories.
"""
from __future__ import annotations

from app.handlers.base import HandlerResult
from app.router.intent import Classification
from app.router.narrate import narrate
from app.services.periods import resolve_period
from app.tools import spending


async def handle_spending(session, user_id, message, cls: Classification, ctx_prefix):
    period = resolve_period(message)
    category = cls.category
    text = message.lower()
    used = ["sql.spending"]

    if any(w in text for w in ("biggest", "largest", "most expensive", "biggest purchase")):
        biggest = await spending.biggest_purchase(
            session, user_id, period.start, period.end, category
        )
        if not biggest:
            fallback = f"I couldn't find any spending in {period.label}."
        else:
            fallback = (
                f"Your biggest purchase in {period.label} was "
                f"${biggest['amount']:.2f} at {biggest['merchant']} "
                f"({biggest['category']}) on {biggest['date']}."
            )
        facts = {"period": period.label, "biggest_purchase": biggest}
        answer = await narrate(message, facts, fallback, ctx_prefix)
        return HandlerResult(answer, "sql", facts, used)

    total = await spending.total_spend(session, user_id, period.start, period.end, category)
    facts = {"period": period.label, "category": category or "all",
             "total_spent": round(total, 2)}
    if category:
        fallback = f"You spent ${total:.2f} on {category} in {period.label}."
    else:
        breakdown = await spending.spend_by_category(session, user_id, period.start, period.end, 6)
        facts["top_categories"] = breakdown
        used.append("sql.spend_by_category")
        top = ", ".join(f"{b['category']} ${b['total']:.0f}" for b in breakdown[:3])
        fallback = (f"You spent ${total:.2f} in total during {period.label}."
                    + (f" Top categories: {top}." if breakdown else ""))
    answer = await narrate(message, facts, fallback, ctx_prefix)
    return HandlerResult(answer, "sql", facts, used)


async def handle_time_comparison(session, user_id, message, cls: Classification, ctx_prefix):
    category = cls.category
    series = await spending.monthly_series(session, user_id, category, months=6)
    used = ["sql.monthly_series"]
    if len(series) < 2:
        fallback = "I don't have enough history yet to compare across time."
        facts = {"series": series}
        return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                             "sql", facts, used)

    current = series[-1]
    prior = series[:-1]
    avg_prior = sum(s["total"] for s in prior) / len(prior)
    delta = current["total"] - avg_prior
    pct = (delta / avg_prior * 100) if avg_prior else 0.0
    direction = "more" if delta > 0 else "less"
    scope = f"on {category}" if category else "overall"
    fallback = (
        f"This month you've spent ${current['total']:.0f} {scope}, "
        f"{abs(pct):.0f}% {direction} than your recent average of "
        f"${avg_prior:.0f}."
    )
    facts = {"category": category or "all", "this_month": current,
             "recent_average": round(avg_prior, 2), "delta": round(delta, 2),
             "pct_change": round(pct, 1), "series": series}
    return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                         "sql", facts, used)


async def handle_summary(session, user_id, message, cls: Classification, ctx_prefix):
    period = resolve_period(message if any(
        k in message.lower() for k in ("month", "year", "week", "day")) else "this month")
    total = await spending.total_spend(session, user_id, period.start, period.end)
    income = await spending.total_income(session, user_id, period.start, period.end)
    by_cat = await spending.spend_by_category(session, user_id, period.start, period.end, 8)
    merchants = await spending.top_merchants(session, user_id, period.start, period.end, 5)
    net = income - total
    used = ["sql.summary"]

    top = ", ".join(f"{b['category']} (${b['total']:.0f})" for b in by_cat[:4])
    fallback = (
        f"In {period.label} you earned ${income:.0f} and spent ${total:.0f} "
        f"(net ${net:+.0f}). Biggest categories: {top or 'none'}."
    )
    facts = {"period": period.label, "income": round(income, 2),
             "spent": round(total, 2), "net": round(net, 2),
             "by_category": by_cat, "top_merchants": merchants}
    return HandlerResult(await narrate(message, facts, fallback, ctx_prefix),
                         "sql", facts, used)
