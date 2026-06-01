"""Data ingestion endpoints: CSV upload and the mock-bank connector."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.models import User
from app.schemas import ImportResult
from app.services.ingestion import (
    generate_mock_bank,
    parse_csv,
    persist_transactions,
)

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/csv", response_model=ImportResult)
async def import_csv(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1", errors="replace")

    parsed = parse_csv(content)
    if not parsed.rows and parsed.errors:
        raise HTTPException(400, "; ".join(parsed.errors))

    return await persist_transactions(
        session, user.id, parsed.rows, source="csv",
        rejected=parsed.rejected, parse_errors=parsed.errors,
    )


@router.post("/mock-bank", response_model=ImportResult)
async def import_mock_bank(
    months: int = Query(12, ge=1, le=60),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Simulate connecting a bank account by generating realistic history."""
    rows = generate_mock_bank(months=months, seed=user.id or 42)
    return await persist_transactions(session, user.id, rows, source="mock_bank")
