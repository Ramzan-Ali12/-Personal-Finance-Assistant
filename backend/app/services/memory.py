"""User-context memory (capability #10).

Stores small, durable preferences the assistant should apply later, and renders
them as a compact system-prompt prefix. Parsing is heuristic-first (cheap and
predictable); the raw phrasing is always kept so nothing is lost.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserContext


async def load_context(session: AsyncSession, user_id: int) -> list[UserContext]:
    rows = await session.execute(
        select(UserContext).where(
            UserContext.user_id == user_id, UserContext.active == True  # noqa: E712
        )
    )
    return list(rows.scalars().all())


async def context_prefix(session: AsyncSession, user_id: int) -> str:
    items = await load_context(session, user_id)
    if not items:
        return ""
    lines = [f"- {c.value}" for c in items]
    return (
        "Known facts and preferences about this user (apply them):\n"
        + "\n".join(lines)
    )


def _parse_fact(message: str) -> tuple[str, str]:
    """Return (key, canonical_value) from a 'remember' message."""
    text = message.strip()
    low = text.lower()

    m = re.search(r"paid on the (\d{1,2})(?:st|nd|rd|th)?", low)
    if m:
        return "payday", f"User is paid on day {m.group(1)} of the month."

    m = re.search(r"(?:don'?t|do not) count (.+?) in (?:my )?(.+?) budget", low)
    if m:
        return "budget_exclusion", f"Do not count {m.group(1).strip()} in the {m.group(2).strip()} budget."

    # Generic: strip a leading 'remember that' / 'note that'.
    cleaned = re.sub(r"^(please\s+)?(remember|note)( that)?[:,]?\s*", "", text,
                     flags=re.IGNORECASE).strip()
    return "note", cleaned or text


async def remember(session: AsyncSession, user_id: int, message: str) -> UserContext:
    key, value = _parse_fact(message)
    # Upsert-by-key for singletons like payday; notes accumulate.
    if key in ("payday",):
        existing = await session.execute(
            select(UserContext).where(
                UserContext.user_id == user_id, UserContext.key == key
            )
        )
        row = existing.scalars().first()
        if row:
            row.value = value
            row.raw_text = message
            row.active = True
            await session.commit()
            await session.refresh(row)
            return row

    ctx = UserContext(user_id=user_id, key=key, value=value, raw_text=message)
    session.add(ctx)
    await session.commit()
    await session.refresh(ctx)
    return ctx
