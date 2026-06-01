"""RAG handler — semantic retrieval over transaction history (pgvector).

Used for free-form / fuzzy questions that aren't a clean aggregation
("what did I buy that was coffee-related?", "anything about travel?"). We never
load the whole history: we embed the query and pull only the top-k nearest
transactions via a pgvector index, then summarise just those. This is the
concrete "large context" strategy — retrieval keeps the prompt tiny no matter
how big the dataset grows.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.base import HandlerResult
from app.llm.embeddings import embedder
from app.router.narrate import narrate
from app.services.vector_search import search_similar_transactions


async def handle_semantic(
    session: AsyncSession, user_id: int, message: str, cls, ctx_prefix: str,
    k: int = 12,
):
    used = ["rag.vector_search"]
    vec = await embedder.embed(message)
    rows = await search_similar_transactions(session, user_id, vec, k)

    if not rows:
        fallback = ("I couldn't find anything relevant in your transactions. "
                    "Try rephrasing, or ask about a specific category or period.")
        return HandlerResult(fallback, "rag", {"matches": []}, used,
                             notes=["no embedded transactions matched"])

    matches = [{
        "merchant": t.merchant,
        "amount": round(-t.amount, 2) if t.amount < 0 else round(t.amount, 2),
        "direction": "spend" if t.amount < 0 else "income",
        "date": t.txn_date.isoformat(),
        "category": t.category,
        "description": t.description,
    } for t in rows]

    spend_total = sum(m["amount"] for m in matches if m["direction"] == "spend")
    preview = ", ".join(f"{m['merchant']} ${m['amount']:.0f}" for m in matches[:5])
    fallback = (f"I found {len(matches)} related transactions "
                f"(about ${spend_total:.0f} of spending). Examples: {preview}.")
    facts = {"matches": matches, "related_spend_total": round(spend_total, 2)}
    answer = await narrate(message, facts, fallback, ctx_prefix)
    return HandlerResult(answer, "rag", facts, used)
