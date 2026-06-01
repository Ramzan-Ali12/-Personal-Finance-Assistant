"""Conversational assistant endpoints.

`POST /api/chat`        -> single JSON response (simple, reliable; used by UI).
`POST /api/chat/stream` -> Server-Sent Events, honouring the streaming design
                           in the architecture (answer computed once, then
                           streamed for a responsive feel — works in mock mode).
`GET  /api/chat/history`-> recent conversation for this user.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.models import ChatMessage, User
from app.router.orchestrator import handle_chat
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await handle_chat(session, user, body.message, body.image_base64)
    return ChatResponse(answer=result.answer, route=result.route, data=result.data,
                        used_tools=result.used_tools, notes=result.notes)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # All DB work happens up-front; the stream only replays the final text.
    result = await handle_chat(session, user, body.message, body.image_base64)

    async def event_gen():
        meta = {"route": result.route, "used_tools": result.used_tools,
                "notes": result.notes}
        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
        for token in result.answer.split(" "):
            yield f"data: {json.dumps({'delta': token + ' '})}\n\n"
            await asyncio.sleep(0.012)
        yield f"event: done\ndata: {json.dumps({'answer': result.answer, 'data': result.data})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/history")
async def history(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
):
    rows = (await session.execute(
        select(ChatMessage).where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc()).limit(limit)
    )).scalars().all()
    rows = list(reversed(rows))
    return [{"role": m.role, "content": m.content, "route": m.route,
             "created_at": m.created_at.isoformat()} for m in rows]
