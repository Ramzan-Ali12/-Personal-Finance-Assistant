"""User-context (memory) management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.models import User, UserContext
from app.schemas import ContextCreate, ContextOut
from app.services.memory import load_context

router = APIRouter(prefix="/api/context", tags=["context"])


@router.get("", response_model=list[ContextOut])
async def list_context(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    items = await load_context(session, user.id)
    return [ContextOut(id=c.id, key=c.key, value=c.value, raw_text=c.raw_text,
                       active=c.active) for c in items]


@router.post("", response_model=ContextOut, status_code=201)
async def add_context(
    body: ContextCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ctx = UserContext(user_id=user.id, key=body.key, value=body.value,
                      raw_text=body.raw_text or body.value)
    session.add(ctx)
    await session.commit()
    await session.refresh(ctx)
    return ContextOut(id=ctx.id, key=ctx.key, value=ctx.value,
                      raw_text=ctx.raw_text, active=ctx.active)


@router.delete("/{ctx_id}", status_code=204)
async def delete_context(
    ctx_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ctx = await session.get(UserContext, ctx_id)
    if not ctx or ctx.user_id != user.id:
        raise HTTPException(404, "Context not found")
    await session.delete(ctx)
    await session.commit()
