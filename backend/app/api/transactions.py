"""Transaction listing and manual entry."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.llm.embeddings import embedder
from app.models import Transaction, User
from app.schemas import TransactionCreate, TransactionOut, TransactionPage
from app.services.categorize import categorize
from app.services.ingestion import NormalizedTxn

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id, txn_date=t.txn_date, amount=t.amount, currency=t.currency,
        merchant=t.merchant, description=t.description, category=t.category,
        account=t.account, is_recurring=t.is_recurring, source=t.source,
    )


@router.get("", response_model=TransactionPage)
async def list_transactions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, le=200),
    offset: int = 0,
    category: str | None = None,
    start: date | None = None,
    end: date | None = None,
    search: str | None = None,
):
    conds = [Transaction.user_id == user.id]
    if category:
        conds.append(Transaction.category == category)
    if start:
        conds.append(Transaction.txn_date >= start)
    if end:
        conds.append(Transaction.txn_date <= end)
    if search:
        conds.append(Transaction.merchant.ilike(f"%{search}%"))

    total = (await session.execute(
        select(func.count()).select_from(Transaction).where(*conds)
    )).scalar_one()

    rows = (await session.execute(
        select(Transaction).where(*conds)
        .order_by(Transaction.txn_date.desc(), Transaction.id.desc())
        .limit(limit).offset(offset)
    )).scalars().all()

    return TransactionPage(
        items=[_to_out(t) for t in rows], total=int(total),
        limit=limit, offset=offset,
    )


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    category = (body.category or "").strip().lower() or categorize(body.merchant, body.description)
    norm = NormalizedTxn(
        txn_date=body.txn_date, amount=body.amount, merchant=body.merchant,
        description=body.description, category=category, account=body.account,
        currency=body.currency,
    )
    vec = await embedder.embed(f"{body.merchant} {body.description} {category}")
    txn = Transaction(
        user_id=user.id, txn_date=norm.txn_date, amount=norm.amount,
        currency=norm.currency, merchant=norm.merchant, description=norm.description,
        category=category, account=norm.account, source="manual",
        dedupe_hash=norm.dedupe_hash, embedding=vec,
    )
    session.add(txn)
    await session.commit()
    await session.refresh(txn)
    return _to_out(txn)
