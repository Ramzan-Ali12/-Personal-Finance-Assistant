"""Tests for the deterministic intent router and period parser."""
from datetime import date

from app.router.intent import Intent, classify_rules
from app.services.periods import resolve_period


def test_spending_question_routes_to_sql():
    c = classify_rules("How much did I spend on groceries last month?", has_image=False)
    assert c.intent == Intent.SPENDING
    assert c.category == "groceries"
    assert c.confidence >= 0.7


def test_subscription_question():
    assert classify_rules("show my recurring subscriptions", False).intent == Intent.SUBSCRIPTIONS


def test_anomaly_question():
    assert classify_rules("anything unusual or suspicious recently?", False).intent == Intent.ANOMALIES


def test_remember_routes_to_memory():
    assert classify_rules("remember that I get paid on the 1st", False).intent == Intent.REMEMBER


def test_image_forces_receipt():
    assert classify_rules("here is my receipt", has_image=True).intent == Intent.RECEIPT


def test_freeform_is_semantic():
    c = classify_rules("tell me about my coffee habit", False)
    assert c.intent in (Intent.SEMANTIC, Intent.SPENDING)


def test_period_last_month():
    today = date(2026, 6, 15)
    p = resolve_period("last month", today)
    assert (p.start, p.end) == (date(2026, 5, 1), date(2026, 5, 31))


def test_period_named_month():
    today = date(2026, 6, 15)
    p = resolve_period("how much in March", today)
    assert p.start == date(2026, 3, 1)
