"""
Parse raw Telegram message text into a structured intent dict.

Each intent has at minimum {"type": <str>, ...fields}.

Supported types:
    sale        — user sold something
                  {"type": "sale", "sku_raw": str, "qty": float}
    stock       — user is logging current stock level
                  {"type": "stock", "sku_raw": str, "qty": float}
    kasbon      — customer borrowed on credit
                  {"type": "kasbon", "customer_raw": str, "amount": float}
    repayment   — customer repaid (partial or full)
                  {"type": "repayment", "customer_raw": str, "amount": float | None}
                  amount is None when the owner types "lunas <name>" (full settlement)
    command     — a slash command
                  {"type": "command", "name": str}
    unknown     — could not parse
                  {"type": "unknown", "raw": str}

Parsing rules (applied in order, first match wins):
    /command              -> command intent
    lunas <name>          -> repayment intent (full settlement, amount=None)
    bayar <name> <amount> -> repayment intent (partial)
    kasbon/utang <name> <amount> -> kasbon intent
    stok <item> <n>       -> stock intent
    <item> <n>            -> sale intent (most messages the owner sends)

Amount parsing handles Bahasa shorthand:
    "20rb"    -> 20_000
    "50ribu"  -> 50_000
    "5k"      ->  5_000
    "100000"  -> 100_000
    "3.5"     ->      3.5

Quantity parsing is separate from amount parsing (qty is units, not rupiah):
    "3", "5", "12.5" -> float
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Amount parser (for kasbon rupiah values, M4+)
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"(?P<digits>[\d.,]+)\s*(?P<suffix>rb|ribu|k|jt|juta)?",
    re.IGNORECASE,
)

_SUFFIX_MULT = {
    "rb": 1_000,
    "ribu": 1_000,
    "k": 1_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
}


def parse_amount(text: str) -> float | None:
    """Return an IDR amount from a string like '20rb', '50ribu', '5k', '100000'."""
    m = _AMOUNT_RE.search(text.strip())
    if not m:
        return None
    digits_str = m.group("digits").replace(",", "").replace(".", "")
    try:
        digits = float(digits_str)
    except ValueError:
        return None
    suffix = (m.group("suffix") or "").lower()
    mult = _SUFFIX_MULT.get(suffix, 1)
    return digits * mult


# ---------------------------------------------------------------------------
# Quantity parser (unit counts for sales and stock)
# ---------------------------------------------------------------------------

_QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_qty(text: str) -> float | None:
    """Return the first numeric quantity found in a string."""
    m = _QTY_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

# Words that signal a stock update rather than a sale
_STOCK_TRIGGERS = {"stok", "stock", "sisa", "tersisa", "ada", "tinggal"}

# Words that signal a kasbon (credit) event
_KASBON_TRIGGERS = {"kasbon", "hutang", "utang", "bon", "kredit"}

# Words that signal a repayment event
_REPAYMENT_TRIGGERS = {"bayar", "bayar", "lunasi", "bayarin"}

# Words that signal a full settlement (all debts cleared)
_SETTLEMENT_TRIGGERS = {"lunas"}

# Words to strip before looking up the SKU name
_NOISE_WORDS = _STOCK_TRIGGERS | {
    "pcs",
    "biji",
    "buah",
    "lembar",
    "bungkus",
    "kg",
    "liter",
    "botol",
}


def _normalize(text: str) -> str:
    return text.lower().strip()


def _strip_trailing_number(text: str) -> tuple[str, float | None]:
    """
    Split 'indomie goreng 3' into ('indomie goreng', 3.0).
    Returns (original_text, None) if no trailing number is found.
    """
    m = re.search(r"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*$", text.strip())
    if not m:
        return text.strip(), None
    return m.group(1).strip(), float(m.group(2).replace(",", "."))


def _parse_customer_and_amount(remainder: str) -> tuple[str, float | None]:
    """
    Split 'bu sri 20rb' into ('bu sri', 20000.0).
    If no amount-like token is found, returns (remainder, None).
    """
    # try to find a trailing amount token (digits + optional suffix)
    m = re.search(
        r"^(.*?)\s+(\d+(?:[.,]\d+)?\s*(?:rb|ribu|k|jt|juta)?)\s*$",
        remainder.strip(),
        re.IGNORECASE,
    )
    if not m:
        return remainder.strip(), None
    customer_raw = m.group(1).strip()
    amount = parse_amount(m.group(2))
    return customer_raw, amount


def parse(text: str) -> dict:
    """
    Parse a raw Telegram message and return an intent dict.

    The caller should pass `message.text` directly.
    """
    text = text.strip()

    # --- slash commands ---
    if text.startswith("/"):
        parts = text.split()
        return {"type": "command", "name": parts[0][1:].lower()}

    normalized = _normalize(text)
    tokens = normalized.split()

    if not tokens:
        return {"type": "unknown", "raw": text}

    first = tokens[0]

    # --- full settlement: "lunas bu sri" ---
    if first in _SETTLEMENT_TRIGGERS:
        customer_raw = " ".join(tokens[1:]).strip()
        if not customer_raw:
            return {"type": "unknown", "raw": text}
        return {"type": "repayment", "customer_raw": customer_raw, "amount": None}

    # --- partial repayment: "bayar bu sri 20rb" ---
    if first in _REPAYMENT_TRIGGERS:
        remainder = " ".join(tokens[1:])
        customer_raw, amount = _parse_customer_and_amount(remainder)
        if not customer_raw:
            return {"type": "unknown", "raw": text}
        return {"type": "repayment", "customer_raw": customer_raw, "amount": amount}

    # --- kasbon borrow: "kasbon bu sri 50rb" ---
    if first in _KASBON_TRIGGERS:
        remainder = " ".join(tokens[1:])
        customer_raw, amount = _parse_customer_and_amount(remainder)
        if not customer_raw or not amount:
            return {"type": "unknown", "raw": text}
        return {"type": "kasbon", "customer_raw": customer_raw, "amount": amount}

    # --- stock update: "stok tahu 20", "sisa indomie 5" ---
    if first in _STOCK_TRIGGERS:
        remainder = " ".join(tokens[1:])
        sku_raw, qty = _strip_trailing_number(remainder)
        if qty is None:
            qty = parse_qty(remainder)
            sku_raw = _QTY_RE.sub("", remainder).strip()
        if not sku_raw:
            return {"type": "unknown", "raw": text}
        return {"type": "stock", "sku_raw": sku_raw, "qty": qty}

    # --- sale (default: "<item name> <qty>") ---
    sku_raw, qty = _strip_trailing_number(text)
    if qty is not None and sku_raw:
        return {"type": "sale", "sku_raw": _normalize(sku_raw), "qty": qty}

    # single word or unrecognized
    return {"type": "unknown", "raw": text}
