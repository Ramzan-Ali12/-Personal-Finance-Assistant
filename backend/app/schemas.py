"""API request/response schemas (Pydantic)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


# ---- Auth ----------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    display_name: Optional[str] = None
    created_at: datetime


# ---- Transactions --------------------------------------------------------
class TransactionCreate(BaseModel):
    txn_date: date
    amount: float
    merchant: str = ""
    description: str = ""
    category: Optional[str] = None
    account: str = "default"
    currency: str = "USD"


class TransactionOut(BaseModel):
    id: int
    txn_date: date
    amount: float
    currency: str
    merchant: str
    description: str
    category: str
    account: str
    is_recurring: bool
    source: str


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


# ---- Budgets -------------------------------------------------------------
class BudgetCreate(BaseModel):
    category: Optional[str] = None
    period: str = "monthly"
    limit_amount: float = Field(gt=0)


class BudgetOut(BaseModel):
    id: int
    category: Optional[str]
    period: str
    limit_amount: float


class BudgetStatus(BaseModel):
    budget: BudgetOut
    spent: float
    remaining: float
    pct_used: float
    status: str  # ok | warning | over


# ---- User context / memory ----------------------------------------------
class ContextCreate(BaseModel):
    key: str
    value: str
    raw_text: str = ""


class ContextOut(BaseModel):
    id: int
    key: str
    value: str
    raw_text: str
    active: bool


# ---- Chat ----------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    # Optional base64 data URL of an image (e.g. a receipt photo).
    image_base64: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    route: str
    data: Optional[dict[str, Any]] = None
    used_tools: list[str] = []
    notes: list[str] = []


# ---- Imports -------------------------------------------------------------
class ImportResult(BaseModel):
    inserted: int
    skipped_duplicates: int
    rejected_rows: int
    errors: list[str] = []
