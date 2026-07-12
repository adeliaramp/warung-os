"""
Customer fuzzy lookup.

Maps a free-text name from a Telegram message to the best matching
customer in the database. Matches against display_name first (if set),
then local_code, then initials.

Customer records in production have minimal PII: initials + local code.
The optional display_name field lets the owner type natural names
(e.g. "Bu Sri") which are stored only in this column.
"""

from __future__ import annotations

from rapidfuzz import fuzz

_customer_cache: list[dict] | None = None


def _load_customers() -> list[dict]:
    from bot.db import get_client

    response = (
        get_client()
        .table("customers")
        .select("customer_id, local_code, initials, display_name")
        .eq("is_active", True)
        .execute()
    )
    return response.data or []


def get_customers() -> list[dict]:
    global _customer_cache
    if _customer_cache is None:
        _customer_cache = _load_customers()
    return _customer_cache


def invalidate_cache() -> None:
    global _customer_cache
    _customer_cache = None


def _search_keys(customer: dict) -> list[str]:
    """Return all searchable strings for a customer record."""
    keys = [customer["local_code"], customer["initials"]]
    if customer.get("display_name"):
        keys.append(customer["display_name"])
    return [k for k in keys if k]


def find_customer(query: str, score_cutoff: int = 50) -> dict | None:
    """
    Return the best-matching customer dict for a free-text query, or None
    if no match exceeds score_cutoff.

    Tries each searchable field independently and picks the highest-scoring
    match across all customers and all fields.
    """
    customers = get_customers()
    if not customers:
        return None

    best_score = 0
    best_customer = None

    for customer in customers:
        for key in _search_keys(customer):
            score = fuzz.token_set_ratio(query.lower(), key.lower())
            if score > best_score:
                best_score = score
                best_customer = customer

    if best_score >= score_cutoff:
        return best_customer
    return None


def customer_display(customer: dict) -> str:
    """Return the most human-readable name for a customer."""
    if customer.get("display_name"):
        return customer["display_name"]
    return f"{customer['initials']} ({customer['local_code']})"
