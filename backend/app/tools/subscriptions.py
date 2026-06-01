"""Recurring-subscription detection (capability #3).

Heuristic, not LLM-based: a charge is "recurring" if the same merchant appears
several times at a roughly fixed cadence (weekly/monthly) with a stable amount.
We compute this from the DB directly so it scales and costs nothing per call.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction


async def detect_subscriptions(
    session: AsyncSession, user_id: int, lookback_days: int = 400
) -> list[dict]:
    since = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(Transaction.merchant, Transaction.txn_date, Transaction.amount,
               Transaction.category)
        .where(
            Transaction.user_id == user_id,
            Transaction.amount < 0,
            Transaction.txn_date >= since,
        )
        .order_by(Transaction.txn_date.asc())
    )
    rows = (await session.execute(stmt)).all()

    by_merchant: dict[str, list[tuple[date, float, str]]] = defaultdict(list)
    for merchant, txn_date, amount, category in rows:
        by_merchant[merchant.strip().lower() or "unknown"].append(
            (txn_date, -float(amount), category)
        )

    results: list[dict] = []
    for key, items in by_merchant.items():
        if len(items) < 3:
            continue
        items.sort(key=lambda x: x[0])
        dates = [d for d, _, _ in items]
        amounts = [a for _, a, _ in items]

        intervals = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not intervals:
            continue
        median_interval = statistics.median(intervals)

        if 25 <= median_interval <= 35:
            cadence = "monthly"
        elif 6 <= median_interval <= 8:
            cadence = "weekly"
        elif 12 <= median_interval <= 16:
            cadence = "biweekly"
        else:
            continue  # irregular -> not a subscription

        mean_amt = statistics.mean(amounts)
        # Stable amount? (low relative spread)
        spread = (statistics.pstdev(amounts) / mean_amt) if mean_amt else 1.0
        if spread > 0.35:
            continue

        results.append({
            "merchant": key.title(),
            "cadence": cadence,
            "avg_amount": round(mean_amt, 2),
            "occurrences": len(items),
            "last_charge": dates[-1].isoformat(),
            "category": items[-1][2],
            "est_monthly_cost": round(mean_amt * (30 / median_interval), 2),
        })

    results.sort(key=lambda r: r["est_monthly_cost"], reverse=True)
    return results
