"""Receipt upload -> vision extraction -> recorded expense."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.handlers import vision_handler
from app.models import Receipt, User
from app.schemas import ChatResponse
from app.services.memory import context_prefix

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


@router.post("", response_model=ChatResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    raw = await file.read()
    mime = file.content_type or "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    ctx = await context_prefix(session, user.id)
    result = await vision_handler.handle_receipt(
        session, user.id, "receipt upload", data_url, ctx
    )
    return ChatResponse(answer=result.answer, route=result.route, data=result.data,
                        used_tools=result.used_tools, notes=result.notes)


@router.get("")
async def list_receipts(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        select(Receipt).where(Receipt.user_id == user.id)
        .order_by(Receipt.created_at.desc()).limit(50)
    )).scalars().all()
    return [{"id": r.id, "status": r.status, "note": r.note,
             "transaction_id": r.transaction_id,
             "created_at": r.created_at.isoformat()} for r in rows]
