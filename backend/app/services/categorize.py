"""Lightweight, deterministic merchant -> category classifier.

Categorization is high-volume (runs on every imported row), so it must be
cheap and fast — an LLM call per transaction would violate the cost/latency
constraints. We use a keyword map, which is transparent and good enough for
the common cases. Unknown merchants fall back to "uncategorized" and can be
resolved on demand by the agent's web-search tool (capability #7).
"""
from __future__ import annotations

# Order matters only for readability; matching is substring-based.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("groceries", ("grocery", "supermarket", "whole foods", "trader joe", "aldi",
                    "safeway", "kroger", "tesco", "lidl", "walmart", "costco")),
    ("dining", ("restaurant", "cafe", "coffee", "starbucks", "mcdonald", "kfc",
                "pizza", "burger", "doordash", "ubereats", "uber eats", "grubhub",
                "deliveroo", "diner", "bar ", "pub")),
    ("transport", ("uber", "lyft", "taxi", "metro", "transit", "shell", "exxon",
                   "chevron", "bp ", "gas station", "fuel", "parking", "toll")),
    ("subscriptions", ("netflix", "spotify", "hulu", "disney", "youtube premium",
                       "prime video", "icloud", "google one", "dropbox", "notion",
                       "adobe", "patreon", "audible")),
    ("utilities", ("electric", "water", "gas bill", "internet", "comcast", "at&t",
                   "verizon", "t-mobile", "utility", "power")),
    ("rent", ("rent", "landlord", "property mgmt", "lease")),
    ("housing", ("mortgage", "hoa", "home depot", "ikea", "furniture")),
    ("health", ("pharmacy", "cvs", "walgreens", "doctor", "dental", "clinic",
                "hospital", "gym", "fitness")),
    ("shopping", ("amazon", "ebay", "target", "best buy", "nike", "zara", "h&m",
                  "apple store", "store")),
    ("entertainment", ("cinema", "movie", "theater", "steam", "playstation",
                       "xbox", "concert", "ticketmaster")),
    ("travel", ("airline", "airways", "hotel", "airbnb", "booking.com", "expedia",
                "delta", "united", "marriott", "hilton")),
    ("income", ("payroll", "salary", "direct deposit", "deposit", "refund",
                "interest", "dividend", "reimbursement")),
    ("transfers", ("transfer", "venmo", "zelle", "paypal", "cash app", "withdrawal",
                   "atm")),
    ("fees", ("fee", "charge", "overdraft", "service charge", "interest charged")),
]


def categorize(merchant: str, description: str = "") -> str:
    text = f"{merchant} {description}".lower()
    for category, keywords in _RULES:
        if any(kw in text for kw in keywords):
            return category
    return "uncategorized"


KNOWN_CATEGORIES = sorted({c for c, _ in _RULES} | {"uncategorized", "other"})
