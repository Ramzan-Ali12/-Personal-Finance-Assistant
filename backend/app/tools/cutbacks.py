"""Personalised, numbers-backed cut-back suggestions (capability #9).

We compare this month's spend per category against the user's own trailing
3-month average. Where a discretionary category is running hot, we quantify
the overshoot and suggest a concrete target. Subscriptions are surfaced as
easy wins. All numbers come from SQL aggregates — the LLM only phrases them.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.services.periods import _month_bounds
from app.tools.subscriptions import detect_subscriptions

_DISCRETIONARY = {"dining", "shopping", "entertainment", "transport",
                  "subscriptions", "travel"}


async def suggest_cutbacks(session: AsyncSession, user_id: int) -> list[dict]:
    today = date.today()
    month_start, _ = _month_bounds(today.year, today.month)

    # This month's spend per category.
    cur_stmt = (
        select(Transaction.category, func.sum(-Transaction.amount))
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.amount < 0,
                Transaction.txn_date >= month_start,
            )
        )
        .group_by(Transaction.category)
    )
    current = {c: float(t) for c, t in (await session.execute(cur_stmt)).all()}

    # Trailing 3 full months -> monthly average per category.
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    prev_start = (prev_start - timedelta(days=1)).replace(day=1)
    prev_start = (prev_start - timedelta(days=1)).replace(day=1)
    base_stmt = (
        select(Transaction.category, func.sum(-Transaction.amount))
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.amount < 0,
                Transaction.txn_date >= prev_start,
                Transaction.txn_date < month_start,
            )
        )
        .group_by(Transaction.category)
    )
    baseline = {c: float(t) / 3.0 for c, t in (await session.execute(base_stmt)).all()}

    suggestions: list[dict] = []
    for category, spent in current.items():
        if category not in _DISCRETIONARY:
            continue
        avg = baseline.get(category, 0.0)
        if avg > 0 and spent > avg * 1.15:
            overshoot = spent - avg
            suggestions.append({
                "category": category,
                "this_month": round(spent, 2),
                "typical_month": round(avg, 2),
                "potential_savings": round(overshoot, 2),
                "suggestion": (
                    f"You've spent ${spent:.0f} on {category} this month vs a "
                    f"typical ${avg:.0f}. Trimming back to your norm saves "
                    f"~${overshoot:.0f}."
                ),
            })

    # Subscriptions: cheap recurring wins.
    subs = await detect_subscriptions(session, user_id)
    for s in subs[:3]:
        suggestions.append({
            "category": "subscriptions",
            "merchant": s["merchant"],
            "this_month": s["avg_amount"],
            "potential_savings": s["est_monthly_cost"],
            "suggestion": (
                f"Cancelling {s['merchant']} (${s['avg_amount']:.2f}/{s['cadence']}) "
                f"would save ~${s['est_monthly_cost']:.0f}/month."
            ),
        })

    suggestions.sort(key=lambda x: x["potential_savings"], reverse=True)
    return suggestions
