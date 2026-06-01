"""Query orchestrator — classify, inject memory, dispatch, log.

This is the "core of the system" box in the architecture diagram: one entry
point that routes each message to the cheapest capable handler, threads the
user's remembered context through, and records the exchange.
"""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers import agent_handler, rag_handler, sql_handler, vision_handler
from app.handlers.base import HandlerResult
from app.models import ChatMessage, User
from app.router.intent import Intent, classify
from app.services import memory

_CLARIFY_TEXT = (
    "I want to make sure I help with the right thing. You can ask me things "
    "like: \"how much did I spend on groceries last month\", \"show my "
    "subscriptions\", \"anything unusual recently?\", \"how am I doing against "
    "my budget\", or upload a receipt photo. Could you rephrase your question?"
)


async def handle_chat(
    session: AsyncSession,
    user: User,
    message: str,
    image_data_url: str | None = None,
) -> HandlerResult:
    ctx_prefix = await memory.context_prefix(session, user.id)
    has_image = bool(image_data_url)
    cls = await classify(message, has_image)
    uid = user.id

    if cls.intent == Intent.RECEIPT:
        result = await vision_handler.handle_receipt(
            session, uid, message, image_data_url, ctx_prefix
        )
    elif cls.intent == Intent.REMEMBER:
        ctx = await memory.remember(session, uid, message)
        result = HandlerResult(
            answer=f"Got it — I'll remember that: \"{ctx.value}\"",
            route="memory", data={"stored": {"key": ctx.key, "value": ctx.value}},
            used_tools=["memory.remember"],
        )
    elif cls.intent == Intent.SPENDING:
        result = await sql_handler.handle_spending(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.TIME_COMPARISON:
        result = await sql_handler.handle_time_comparison(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.SUMMARY:
        result = await sql_handler.handle_summary(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.SUBSCRIPTIONS:
        result = await agent_handler.handle_subscriptions(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.ANOMALIES:
        result = await agent_handler.handle_anomalies(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.BUDGET:
        result = await agent_handler.handle_budget(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.CUTBACKS:
        result = await agent_handler.handle_cutbacks(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.MERCHANT_LOOKUP:
        result = await agent_handler.handle_merchant_lookup(session, uid, message, cls, ctx_prefix)
    elif cls.intent == Intent.SEMANTIC:
        result = await rag_handler.handle_semantic(session, uid, message, cls, ctx_prefix)
    else:  # CLARIFY / unknown
        result = HandlerResult(_CLARIFY_TEXT, "clarify", {}, [], ["ambiguous request"])

    result.notes = (result.notes or []) + [f"intent={cls.intent}",
                                            f"confidence={cls.confidence:.2f}",
                                            f"router={cls.source}"]
    await _log(session, uid, message, result)
    return result


async def _log(session: AsyncSession, user_id: int, message: str, result: HandlerResult):
    session.add(ChatMessage(user_id=user_id, role="user", content=message))
    session.add(ChatMessage(
        user_id=user_id, role="assistant", content=result.answer,
        route=result.route,
        meta=json.dumps({"used_tools": result.used_tools, "notes": result.notes}),
    ))
    await session.commit()
