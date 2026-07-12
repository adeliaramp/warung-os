"""
SKU fuzzy lookup.

Maps a free-text item name from a Telegram message to the best matching
SKU in the database. Uses rapidfuzz token_set_ratio so partial or
reordered words still match (e.g. "minyak 1L" → "Minyak Goreng 1L").

The SKU list is cached in memory after the first DB call. Call
`invalidate_cache()` if the catalog changes at runtime.
"""

from __future__ import annotations

from rapidfuzz import fuzz, process

_sku_cache: list[dict] | None = None


def _load_skus() -> list[dict]:
    """Fetch all active SKUs from the database."""
    from bot.db import get_client

    response = (
        get_client().table("skus").select("sku_id, name, unit").eq("is_active", True).execute()
    )
    return response.data or []


def get_skus() -> list[dict]:
    global _sku_cache
    if _sku_cache is None:
        _sku_cache = _load_skus()
    return _sku_cache


def invalidate_cache() -> None:
    global _sku_cache
    _sku_cache = None


def find_sku(query: str, score_cutoff: int = 50) -> dict | None:
    """
    Return the best-matching SKU dict for a free-text query, or None if
    no match exceeds score_cutoff.

    Parameters
    ----------
    query        : the raw item name from the user's message
    score_cutoff : minimum rapidfuzz token_set_ratio score (0-100)
    """
    skus = get_skus()
    if not skus:
        return None

    names = [s["name"] for s in skus]
    result = process.extractOne(
        query,
        names,
        scorer=fuzz.token_set_ratio,
        score_cutoff=score_cutoff,
    )
    if result is None:
        return None

    best_name, score, idx = result
    return skus[idx]
