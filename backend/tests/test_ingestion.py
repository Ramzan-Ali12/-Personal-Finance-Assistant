"""Tests for the messy-CSV parser (no DB required)."""
from app.services.ingestion import parse_csv


SAMPLE = """Date,Description,Merchant,Amount,Category
2026-05-01,Salary,Acme Payroll,4200.00,income
2026-05-03,Groceries,Whole Foods,"-86.40",groceries
2026-05-03,Groceries,Whole Foods,"-86.40",groceries
2026-05-05,Fuel,Shell,(48.10),
2026-05-06,Order,Amazon,"-1,299.99",
2026-05-09,,,,
2026-05-10,Pharmacy,CVS,,health
05/12/2026,Lunch,Chipotle,-12.40,dining
"""


def test_parses_valid_rows_and_rejects_junk():
    out = parse_csv(SAMPLE)
    # Junk row (all blank) and the row missing an amount are rejected.
    assert out.rejected == 2
    # 8 data lines - 2 rejected = 6 parsed (duplicate is kept here; dedup is at persist).
    assert len(out.rows) == 6


def test_amount_sign_and_formatting():
    out = parse_csv(SAMPLE)
    by_merchant = {r.merchant: r.amount for r in out.rows}
    assert by_merchant["Acme Payroll"] == 4200.00          # income positive
    assert by_merchant["Shell"] == -48.10                  # parentheses -> negative
    assert by_merchant["Amazon"] == -1299.99               # thousands separator


def test_category_inferred_when_missing():
    out = parse_csv(SAMPLE)
    amazon = next(r for r in out.rows if r.merchant == "Amazon")
    assert amazon.category == "shopping"  # inferred from keyword map


def test_flexible_date_formats():
    out = parse_csv(SAMPLE)
    chipotle = next(r for r in out.rows if r.merchant == "Chipotle")
    assert chipotle.txn_date.isoformat() == "2026-05-12"
