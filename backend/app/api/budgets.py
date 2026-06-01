"""Budget CRUD + live status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.models import Budget, User
from app.schemas import BudgetCreate, BudgetOut
from app.tools.budgets import budget_status

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("")
async def list_budgets(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return budgets with their live spend/limit status."""
    return await budget_status(session, user.id)


@router.post("", response_model=BudgetOut, status_code=201)
async def create_budget(
    body: BudgetCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    category = (body.category or None)
    if category:
        category = category.strip().lower() or None
    # Upsert on (user, category, period).
    existing = (await session.execute(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category.is_(None) if category is None else Budget.category == category,
            Budget.period == body.period,
        )
    )).scalars().first()
    if existing:
        existing.limit_amount = body.limit_amount
        await session.commit()
        await session.refresh(existing)
        b = existing
    else:
        b = Budget(user_id=user.id, category=category, period=body.period,
                   limit_amount=body.limit_amount)
        session.add(b)
        await session.commit()
        await session.refresh(b)
    return BudgetOut(id=b.id, category=b.category, period=b.period,
                     limit_amount=b.limit_amount)


@router.delete("/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    b = await session.get(Budget, budget_id)
    if not b or b.user_id != user.id:
        raise HTTPException(404, "Budget not found")
    await session.delete(b)
    await session.commit()
