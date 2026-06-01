"""Deterministic spending aggregations (SQL only, no LLM).

These are the workhorse for "how much did I spend" style questions. Pushing
the math into Postgres means it stays O(index scan) regardless of whether the
user has 1 month or 10 years of data — the model never sees raw rows, only
small aggregates. This is the core answer to the "large context" constraint.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction

# Spending = outflows (amount < 0). We report it as a positive number.
_SPEND = Transaction.amount < 0


def _scope(user_id: int, start: date, end: date, category: str | None = None):
    conds = [
        Transaction.user_id == user_id,
        Transaction.txn_date >= start,
        Transaction.txn_date <= end,
    ]
    if category:
        conds.append(Transaction.category == category)
    return and_(*conds)


async def total_spend(
    session: AsyncSession, user_id: int, start: date, end: date,
    category: str | None = None,
) -> float:
    stmt = select(func.coalesce(func.sum(-Transaction.amount), 0.0)).where(
        _scope(user_id, start, end, category), _SPEND
    )
    return float((await session.execute(stmt)).scalar_one())


async def total_income(
    session: AsyncSession, user_id: int, start: date, end: date
) -> float:
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(
        _scope(user_id, start, end), Transaction.amount > 0
    )
    return float((await session.execute(stmt)).scalar_one())


async def spend_by_category(
    session: AsyncSession, user_id: int, start: date, end: date, limit: int = 20
) -> list[dict]:
    stmt = (
        select(Transaction.category, func.sum(-Transaction.amount).label("total"))
        .where(_scope(user_id, start, end), _SPEND)
        .group_by(Transaction.category)
        .order_by(func.sum(-Transaction.amount).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [{"category": c, "total": round(float(t), 2)} for c, t in rows]


async def top_merchants(
    session: AsyncSession, user_id: int, start: date, end: date, limit: int = 10
) -> list[dict]:
    stmt = (
        select(
            Transaction.merchant,
            func.sum(-Transaction.amount).label("total"),
            func.count().label("n"),
        )
        .where(_scope(user_id, start, end), _SPEND)
        .group_by(Transaction.merchant)
        .order_by(func.sum(-Transaction.amount).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"merchant": m, "total": round(float(t), 2), "count": int(n)}
        for m, t, n in rows
    ]


async def biggest_purchase(
    session: AsyncSession, user_id: int, start: date, end: date,
    category: str | None = None,
) -> dict | None:
    stmt = (
        select(Transaction)
        .where(_scope(user_id, start, end, category), _SPEND)
        .order_by(Transaction.amount.asc())  # most negative = biggest spend
        .limit(1)
    )
    txn = (await session.execute(stmt)).scalars().first()
    if not txn:
        return None
    return {
        "merchant": txn.merchant,
        "amount": round(-txn.amount, 2),
        "date": txn.txn_date.isoformat(),
        "category": txn.category,
        "description": txn.description,
    }


async def monthly_series(
    session: AsyncSession, user_id: int, category: str | None = None,
    months: int = 24,
) -> list[dict]:
    """Per-month spend totals — small, cheap, and ideal for trend reasoning."""
    month = func.date_trunc("month", Transaction.txn_date)
    conds = [Transaction.user_id == user_id, _SPEND]
    if category:
        conds.append(Transaction.category == category)
    stmt = (
        select(month.label("m"), func.sum(-Transaction.amount).label("total"))
        .where(and_(*conds))
        .group_by(month)
        .order_by(month.desc())
        .limit(months)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"month": m.date().isoformat() if hasattr(m, "date") else str(m),
         "total": round(float(t), 2)}
        for m, t in reversed(rows)
    ]
