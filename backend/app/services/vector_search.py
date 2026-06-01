"""Vector similarity search over transaction embeddings.

Embeddings are stored as JSON so the app runs on standard Postgres without
pgvector. Similarity is computed in-process over a capped recent window, which
keeps latency bounded as history grows.
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction

_CANDIDATE_LIMIT = 2500


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def search_similar_transactions(
    session: AsyncSession,
    user_id: int,
    query_vec: list[float],
    k: int = 12,
) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.embedding.is_not(None))
        .order_by(Transaction.txn_date.desc())
        .limit(_CANDIDATE_LIMIT)
    )
    txns = (await session.execute(stmt)).scalars().all()
    scored = [
        (cosine_similarity(query_vec, t.embedding), t)
        for t in txns
        if t.embedding
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [t for _, t in scored[:k]]
