"""Database models (SQLModel).

Amount convention (normalized at ingestion time, see services/ingestion.py):
    amount < 0  -> money OUT  (spending / debit)
    amount > 0  -> money IN   (income / refund / credit)

This single signed convention keeps every aggregation query simple and
unambiguous regardless of how the source CSV / bank formatted things.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Column, Index, UniqueConstraint, func
from sqlmodel import Field, SQLModel

from app.config import settings

EMBED_DIM = settings.embeddings_dim


def _utcnow() -> datetime:
    return datetime.utcnow()


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    display_name: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    __table_args__ = (
        # One physical transaction per user — protects against duplicate imports.
        UniqueConstraint("user_id", "dedupe_hash", name="uq_txn_user_dedupe"),
        Index("ix_txn_user_date", "user_id", "txn_date"),
        Index("ix_txn_user_category", "user_id", "category"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)

    txn_date: date = Field(nullable=False)
    amount: float = Field(nullable=False)              # signed; see module docstring
    currency: str = Field(default="USD")

    merchant: str = Field(default="", index=True)
    description: str = Field(default="")
    category: str = Field(default="uncategorized", index=True)
    account: str = Field(default="default")

    is_recurring: bool = Field(default=False)          # set by subscription detection
    source: str = Field(default="csv")                 # csv | mock_bank | receipt | manual
    dedupe_hash: str = Field(nullable=False, index=True)

    # Semantic vector for RAG (JSON list — works without pgvector; upgraded at query
    # time when the pgvector extension is installed).
    embedding: Optional[list[float]] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class Budget(SQLModel, table=True):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "period", name="uq_budget_user_cat"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    # category=None means an overall (all-spending) budget.
    category: Optional[str] = Field(default=None, index=True)
    period: str = Field(default="monthly")             # monthly | weekly
    limit_amount: float = Field(nullable=False)        # positive number, in currency
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class UserContext(SQLModel, table=True):
    """Durable user memory (capability #10).

    Stores small facts/preferences the assistant should remember and apply,
    e.g. "paid on the 1st" or "don't count rent in food budget". These are
    injected as a compact system-prompt prefix on every LLM call.
    """

    __tablename__ = "user_context"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    key: str = Field(nullable=False)                   # short slug, e.g. "payday"
    value: str = Field(nullable=False)                 # canonical value
    raw_text: str = Field(default="")                  # original user phrasing
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": func.now()},
    )


class Receipt(SQLModel, table=True):
    __tablename__ = "receipts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    transaction_id: Optional[int] = Field(
        default=None, foreign_key="transactions.id"
    )
    image_path: str = Field(nullable=False)
    status: str = Field(default="pending")             # pending|extracted|low_confidence|failed
    extracted_json: Optional[str] = None               # JSON string of extraction
    note: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_user_created", "user_id", "created_at"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    role: str = Field(nullable=False)                  # user | assistant
    content: str = Field(nullable=False)
    route: Optional[str] = None                        # which handler answered
    meta: Optional[str] = None                         # JSON: tokens, tools used, etc.
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
