"""Transaction ingestion: CSV parsing, cleaning, dedup, and persistence.

Real-world data is messy (the brief calls this out explicitly), so the parser
is deliberately defensive:
  * flexible column-name aliases (date/amount/debit/credit/merchant/...),
  * tolerant date and money parsing,
  * junk/empty rows are *rejected and counted*, never silently dropped,
  * duplicates are de-duplicated via a content hash (idempotent re-imports).
"""
from __future__ import annotations

import csv
import hashlib
import io
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import embedder
from app.models import Transaction
from app.schemas import ImportResult
from app.services.categorize import categorize

# --- Column aliases -------------------------------------------------------
_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "txn date", "posted date", "posted",
             "transaction_date"),
    "amount": ("amount", "amt", "value", "transaction amount"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out", "outflow"),
    "credit": ("credit", "deposit", "deposits", "money in", "inflow"),
    "description": ("description", "desc", "memo", "details", "narrative", "notes"),
    "merchant": ("merchant", "payee", "name", "vendor", "counterparty"),
    "category": ("category", "cat", "type"),
    "currency": ("currency", "ccy"),
    "account": ("account", "account name", "account_id"),
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
    "%Y/%m/%d", "%m/%d/%y", "%d/%m/%y", "%b %d, %Y", "%d %b %Y",
)


@dataclass
class NormalizedTxn:
    txn_date: date
    amount: float
    merchant: str
    description: str
    category: str
    account: str = "default"
    currency: str = "USD"

    @property
    def dedupe_hash(self) -> str:
        key = f"{self.txn_date.isoformat()}|{round(self.amount, 2)}|" \
              f"{self.merchant.lower().strip()}|{self.description.lower().strip()}|" \
              f"{self.account.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()


@dataclass
class ParseOutput:
    rows: list[NormalizedTxn] = field(default_factory=list)
    rejected: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_amount(raw: str) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = s.replace("$", "").replace("€", "").replace("£", "").replace(",", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def _parse_date(raw: str) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # ISO with time component
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Map canonical field -> actual CSV column name."""
    lower = {fn.lower().strip(): fn for fn in fieldnames if fn}
    mapping: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in lower:
                mapping[canonical] = lower[alias]
                break
    return mapping


def parse_csv(content: str) -> ParseOutput:
    out = ParseOutput()
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        out.errors.append("CSV has no header row.")
        return out

    hmap = _build_header_map(reader.fieldnames)
    if "date" not in hmap:
        out.errors.append("Could not find a recognisable 'date' column.")
        return out
    has_amount = "amount" in hmap
    has_debit_credit = "debit" in hmap or "credit" in hmap
    if not (has_amount or has_debit_credit):
        out.errors.append("Could not find an 'amount' (or debit/credit) column.")
        return out

    for lineno, row in enumerate(reader, start=2):
        txn_date = _parse_date(row.get(hmap["date"], ""))
        if txn_date is None:
            out.rejected += 1
            continue

        # Resolve a single signed amount.
        amount: float | None = None
        if has_amount:
            amount = _parse_amount(row.get(hmap["amount"], ""))
        if amount is None and has_debit_credit:
            debit = _parse_amount(row.get(hmap.get("debit", ""), "")) if "debit" in hmap else None
            credit = _parse_amount(row.get(hmap.get("credit", ""), "")) if "credit" in hmap else None
            if debit:
                amount = -abs(debit)        # debit = money out
            elif credit:
                amount = abs(credit)        # credit = money in
        if amount is None or amount == 0:
            out.rejected += 1
            continue

        merchant = (row.get(hmap.get("merchant", ""), "") or "").strip()
        description = (row.get(hmap.get("description", ""), "") or "").strip()
        if not merchant and not description:
            # Junk row with no identifying info.
            out.rejected += 1
            continue
        if not merchant:
            merchant = description[:60]

        category = (row.get(hmap.get("category", ""), "") or "").strip().lower()
        if not category:
            category = categorize(merchant, description)

        out.rows.append(
            NormalizedTxn(
                txn_date=txn_date,
                amount=amount,
                merchant=merchant,
                description=description,
                category=category,
                account=(row.get(hmap.get("account", ""), "") or "default").strip() or "default",
                currency=(row.get(hmap.get("currency", ""), "") or "USD").strip() or "USD",
            )
        )
    return out


async def persist_transactions(
    session: AsyncSession,
    user_id: int,
    rows: list[NormalizedTxn],
    source: str,
    rejected: int = 0,
    parse_errors: list[str] | None = None,
) -> ImportResult:
    """Insert normalized rows, skipping duplicates (idempotent)."""
    errors = list(parse_errors or [])
    if not rows:
        return ImportResult(inserted=0, skipped_duplicates=0, rejected_rows=rejected,
                            errors=errors)

    # Existing hashes for this user (one query) + in-batch dedup.
    existing = await session.execute(
        select(Transaction.dedupe_hash).where(Transaction.user_id == user_id)
    )
    seen: set[str] = set(existing.scalars().all())

    inserted = 0
    skipped = 0
    to_embed: list[NormalizedTxn] = []
    for r in rows:
        h = r.dedupe_hash
        if h in seen:
            skipped += 1
            continue
        seen.add(h)
        to_embed.append(r)

    # Embed in one batch (local embedder is instant; API embedder batches).
    vectors = await embedder.embed_many(
        [f"{r.merchant} {r.description} {r.category}" for r in to_embed]
    )

    for r, vec in zip(to_embed, vectors):
        session.add(
            Transaction(
                user_id=user_id,
                txn_date=r.txn_date,
                amount=r.amount,
                currency=r.currency,
                merchant=r.merchant,
                description=r.description,
                category=r.category,
                account=r.account,
                source=source,
                dedupe_hash=r.dedupe_hash,
                embedding=vec,
            )
        )
        inserted += 1

    await session.commit()
    return ImportResult(
        inserted=inserted,
        skipped_duplicates=skipped,
        rejected_rows=rejected,
        errors=errors,
    )


# --- Mock bank ------------------------------------------------------------
_MOCK_MERCHANTS = [
    ("Whole Foods Market", "groceries", (40, 120)),
    ("Trader Joe's", "groceries", (25, 80)),
    ("Starbucks", "dining", (4, 12)),
    ("Chipotle", "dining", (9, 18)),
    ("Uber", "transport", (8, 35)),
    ("Shell Gas", "transport", (30, 70)),
    ("Amazon", "shopping", (15, 200)),
    ("Target", "shopping", (20, 150)),
    ("CVS Pharmacy", "health", (5, 60)),
]
_MOCK_SUBSCRIPTIONS = [
    ("Netflix", "subscriptions", 15.49),
    ("Spotify", "subscriptions", 10.99),
    ("Adobe Creative Cloud", "subscriptions", 54.99),
    ("PlanetFitness Gym", "health", 24.99),
]


def generate_mock_bank(months: int = 12, seed: int = 42) -> list[NormalizedTxn]:
    """Deterministically generate a realistic multi-month transaction history.

    Includes salary (income), monthly subscriptions, recurring spend, and a
    couple of deliberate anomalies so every assistant capability is demoable.
    """
    rng = random.Random(seed)
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=30 * months))
    rows: list[NormalizedTxn] = []

    cursor = start
    while cursor <= today:
        # Salary on the 1st of each month.
        if cursor.day == 1:
            rows.append(NormalizedTxn(cursor, 4200.0, "Acme Corp Payroll",
                                      "Direct deposit salary", "income"))
            for name, cat, amt in _MOCK_SUBSCRIPTIONS:
                rows.append(NormalizedTxn(cursor, -amt, name, "Monthly subscription", cat))
            # Rent on the 1st.
            rows.append(NormalizedTxn(cursor, -1500.0, "Skyline Property Mgmt",
                                      "Monthly rent", "rent"))

        # A few random daily spends.
        for _ in range(rng.randint(0, 3)):
            name, cat, (lo, hi) = rng.choice(_MOCK_MERCHANTS)
            amt = round(rng.uniform(lo, hi), 2)
            rows.append(NormalizedTxn(cursor, -amt, name, f"{name} purchase", cat))
        cursor += timedelta(days=1)

    # Inject anomalies in the most recent month.
    rows.append(NormalizedTxn(today - timedelta(days=3), -1899.00, "Best Buy",
                              "Large electronics purchase", "shopping"))
    rows.append(NormalizedTxn(today - timedelta(days=1), -640.00, "SQH*UNKNOWN-MERCHANT",
                              "Unrecognised charge", "uncategorized"))
    return rows
