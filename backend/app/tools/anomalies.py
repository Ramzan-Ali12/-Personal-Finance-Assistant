"""Unusual-activity detection (capability #4).

We build a per-category baseline (mean + std of spend) from the user's own
history and flag recent charges that sit well outside their normal pattern.
"Unusual" is relative to *this* user, not a global rule. Stats are computed in
SQL; only the small set of recent candidates is examined in Python.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction


async def detect_anomalies(
    session: AsyncSession,
    user_id: int,
    recent_days: int = 30,
    z_threshold: float = 2.5,
    abs_floor: float = 75.0,
) -> list[dict]:
    # Per-category baseline over full history (spend only).
    base_stmt = (
        select(
            Transaction.category,
            func.avg(-Transaction.amount).label("mean"),
            func.coalesce(func.stddev_samp(-Transaction.amount), 0.0).label("std"),
            func.count().label("n"),
        )
        .where(Transaction.user_id == user_id, Transaction.amount < 0)
        .group_by(Transaction.category)
    )
    baselines = {
        cat: {"mean": float(mean or 0), "std": float(std or 0), "n": int(n)}
        for cat, mean, std, n in (await session.execute(base_stmt)).all()
    }

    since = date.today() - timedelta(days=recent_days)
    recent_stmt = (
        select(Transaction)
        .where(
            and_(
                Transaction.user_id == user_id,
                Transaction.amount < 0,
                Transaction.txn_date >= since,
            )
        )
        .order_by(Transaction.txn_date.desc())
    )
    recent = (await session.execute(recent_stmt)).scalars().all()

    anomalies: list[dict] = []
    for txn in recent:
        amount = -txn.amount
        if amount < abs_floor:
            continue
        base = baselines.get(txn.category)
        reason = None
        score = 0.0
        if base and base["n"] >= 5 and base["std"] > 0:
            score = (amount - base["mean"]) / base["std"]
            if score >= z_threshold:
                reason = (
                    f"{amount:.0f} is {score:.1f}x your usual "
                    f"{txn.category} spend (~{base['mean']:.0f})."
                )
        elif txn.category in ("uncategorized", "other") and amount >= abs_floor * 2:
            reason = f"Large charge from an unrecognised/uncategorised merchant."
            score = 3.0
        if reason:
            anomalies.append({
                "merchant": txn.merchant,
                "amount": round(amount, 2),
                "date": txn.txn_date.isoformat(),
                "category": txn.category,
                "z_score": round(score, 2),
                "reason": reason,
            })

    anomalies.sort(key=lambda a: a["z_score"], reverse=True)
    return anomalies
