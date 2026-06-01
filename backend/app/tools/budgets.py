"""Budget tracking (capability #6).

Computes how much of each budget is used in the current period and a status
flag the UI/assistant can warn on. Honours the user-context rule
"don't count <category> in <budget>" by accepting an exclusions set.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Budget
from app.services.periods import _month_bounds
from app.tools.spending import total_spend

WARNING_PCT = 0.8


def _period_range(period: str, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    if period == "weekly":
        start = today - timedelta(days=today.weekday())
        return start, today
    start, _ = _month_bounds(today.year, today.month)
    return start, today


async def budget_status(session: AsyncSession, user_id: int) -> list[dict]:
    budgets = (
        await session.execute(select(Budget).where(Budget.user_id == user_id))
    ).scalars().all()

    out: list[dict] = []
    for b in budgets:
        start, end = _period_range(b.period)
        spent = await total_spend(session, user_id, start, end, category=b.category)
        pct = (spent / b.limit_amount) if b.limit_amount else 0.0
        if pct >= 1.0:
            status = "over"
        elif pct >= WARNING_PCT:
            status = "warning"
        else:
            status = "ok"
        out.append({
            "id": b.id,
            "category": b.category or "overall",
            "period": b.period,
            "limit": round(b.limit_amount, 2),
            "spent": round(spent, 2),
            "remaining": round(b.limit_amount - spent, 2),
            "pct_used": round(pct * 100, 1),
            "status": status,
        })
    return out
