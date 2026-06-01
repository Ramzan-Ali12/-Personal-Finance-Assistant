"""Seed a demo user with realistic data so the app is explorable immediately.

Run with:  python -m app.seed
Idempotent: re-running won't duplicate the demo user or its transactions.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from app.auth.security import hash_password
from app.db import async_session_factory, init_db
from app.models import Budget, User, UserContext
from app.services.ingestion import (
    generate_mock_bank,
    parse_csv,
    persist_transactions,
)

DEMO_EMAIL = "demo@finance.app"
DEMO_PASSWORD = "demo1234"


async def seed() -> None:
    await init_db()
    async with async_session_factory() as session:
        existing = (await session.execute(
            select(User).where(User.email == DEMO_EMAIL)
        )).scalars().first()

        if existing:
            user = existing
            print(f"Demo user already exists (id={user.id}).")
        else:
            user = User(email=DEMO_EMAIL,
                        hashed_password=hash_password(DEMO_PASSWORD),
                        display_name="Demo User")
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"Created demo user {DEMO_EMAIL} / {DEMO_PASSWORD} (id={user.id}).")

        # 1) Mock-bank history (12 months).
        mock_rows = generate_mock_bank(months=12, seed=user.id)
        r1 = await persist_transactions(session, user.id, mock_rows, source="mock_bank")
        print(f"Mock bank: +{r1.inserted} inserted, {r1.skipped_duplicates} dup.")

        # 2) Sample CSV (messy on purpose).
        csv_path = Path(__file__).resolve().parent.parent / "data" / "sample_transactions.csv"
        if csv_path.exists():
            parsed = parse_csv(csv_path.read_text(encoding="utf-8-sig"))
            r2 = await persist_transactions(
                session, user.id, parsed.rows, source="csv",
                rejected=parsed.rejected, parse_errors=parsed.errors,
            )
            print(f"Sample CSV: +{r2.inserted} inserted, {r2.skipped_duplicates} dup, "
                  f"{r2.rejected_rows} rejected junk rows.")

        # 3) A budget and a remembered preference.
        has_budget = (await session.execute(
            select(Budget).where(Budget.user_id == user.id)
        )).scalars().first()
        if not has_budget:
            session.add(Budget(user_id=user.id, category="dining", period="monthly",
                               limit_amount=250))
            session.add(Budget(user_id=user.id, category=None, period="monthly",
                               limit_amount=3000))
            session.add(UserContext(user_id=user.id, key="payday",
                                    value="User is paid on day 1 of the month.",
                                    raw_text="I get paid on the 1st"))
            await session.commit()
            print("Added demo budgets + remembered payday.")

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
