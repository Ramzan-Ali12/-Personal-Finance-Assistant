"""Vision handler — read a receipt photo and record it (capability #2).

Robustness is explicitly required (blurry/rotated/cropped/foreign-language
receipts). We instruct the model to (a) do its best, (b) translate, and
(c) self-report a confidence and any problems. Low-confidence extractions are
saved but flagged for user confirmation rather than silently trusted.

If no vision-capable LLM is configured, we still record the receipt as
`pending` and tell the user how to proceed — we never crash.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.base import HandlerResult
from app.llm.client import llm
from app.llm.embeddings import embedder
from app.models import Receipt, Transaction
from app.services.categorize import categorize
from app.services.ingestion import NormalizedTxn

_EXTRACT_PROMPT = (
    "You are extracting structured data from a photo of a receipt. The image "
    "may be blurry, rotated, partially cut off, or in another language — do "
    "your best and translate to English. Respond with STRICT JSON only:\n"
    "{\n"
    '  "merchant": string,\n'
    '  "date": "YYYY-MM-DD" or null,\n'
    '  "total": number (the grand total, positive),\n'
    '  "currency": 3-letter code (default USD),\n'
    '  "category": one of common spend categories or "uncategorized",\n'
    '  "confidence": number 0..1,\n'
    '  "issues": short string describing any problems (blur, missing total, etc.)\n'
    "}\n"
    "If you cannot read the total, set total to null and confidence low."
)


async def handle_receipt(
    session: AsyncSession,
    user_id: int,
    message: str,
    image_data_url: str | None,
    ctx_prefix: str,
) -> HandlerResult:
    used = ["vision.extract"]
    if not image_data_url:
        return HandlerResult(
            "Please attach a photo of the receipt and I'll record it for you.",
            "vision", {}, used, ["no image provided"],
        )

    # Persist the receipt row first so we never lose the upload.
    receipt = Receipt(user_id=user_id, image_path="(inline base64)", status="pending")
    session.add(receipt)
    await session.commit()
    await session.refresh(receipt)

    if not llm.available:
        receipt.status = "pending"
        receipt.note = "Vision LLM not configured."
        await session.commit()
        return HandlerResult(
            "I've saved your receipt, but automatic reading isn't configured "
            "(no vision model set). Set an LLM API key to enable extraction, or "
            "add the expense manually.",
            "vision", {"receipt_id": receipt.id}, used,
            ["vision model unavailable"],
        )

    # Step 1: extract.
    try:
        raw = await llm.vision(_EXTRACT_PROMPT, image_data_url)
        data = _parse_json(raw)
    except Exception as exc:
        receipt.status = "failed"
        receipt.note = f"extraction error: {exc}"
        await session.commit()
        return HandlerResult(
            "I couldn't read that receipt (the image may be unsupported or the "
            "vision service failed). You can try a clearer photo or add it manually.",
            "vision", {"receipt_id": receipt.id}, used, [str(exc)],
        )

    total = data.get("total")
    confidence = float(data.get("confidence") or 0)
    merchant = (data.get("merchant") or "Unknown merchant").strip()
    issues = data.get("issues") or ""

    receipt.extracted_json = json.dumps(data)

    # Step 2: validate. Missing total or low confidence -> flag, don't auto-book.
    if total is None or total <= 0:
        receipt.status = "low_confidence"
        receipt.note = f"No reliable total. {issues}"
        await session.commit()
        return HandlerResult(
            f"I read the receipt from '{merchant}' but couldn't reliably extract "
            f"the total{f' ({issues})' if issues else ''}. Could you confirm the "
            f"amount so I can record it?",
            "vision", {"receipt_id": receipt.id, "extracted": data}, used,
            ["missing/low-confidence total"],
        )

    txn_date = _parse_date(data.get("date")) or date.today()
    category = (data.get("category") or "").strip().lower() or categorize(merchant)
    norm = NormalizedTxn(
        txn_date=txn_date, amount=-abs(float(total)), merchant=merchant,
        description="Receipt upload", category=category,
        currency=(data.get("currency") or "USD"),
    )
    vec = await embedder.embed(f"{merchant} receipt {category}")
    txn = Transaction(
        user_id=user_id, txn_date=norm.txn_date, amount=norm.amount,
        currency=norm.currency, merchant=merchant, description="Receipt upload",
        category=category, source="receipt", dedupe_hash=norm.dedupe_hash,
        embedding=vec,
    )
    session.add(txn)
    await session.flush()
    receipt.transaction_id = txn.id
    receipt.status = "extracted" if confidence >= 0.5 else "low_confidence"
    await session.commit()

    flag = "" if confidence >= 0.5 else " (low confidence — please double-check)"
    answer = (
        f"Recorded ${abs(norm.amount):.2f} at {merchant} on "
        f"{txn_date.isoformat()} under '{category}'.{flag}"
    )
    facts = {"recorded_transaction": {
        "merchant": merchant, "amount": round(abs(norm.amount), 2),
        "date": txn_date.isoformat(), "category": category,
        "confidence": confidence, "issues": issues}}
    return HandlerResult(answer, "vision", facts, used,
                         notes=[issues] if issues else [])


def _parse_json(text: str) -> dict:
    text = text.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None
