"""
Morning digest job — runs via GitHub Actions cron at 06:00 WIB (23:00 UTC).

Sends a summary to MERCHANT_CHAT_ID containing:
    - Yesterday's sales count
    - Dry goods that need restocking (stock <= ROP from nightly cache)
    - Fresh goods to buy today (newsvendor order qty from nightly cache)

Falls back to the simple 3× daily demand threshold if the nightly
recompute has not yet run (cold start or first day).

M4 will add: kasbon reminders.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_yesterday() -> str:
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _day_name_bahasa(date_str: str) -> str:
    DAY_NAMES = {
        0: "Senin",
        1: "Selasa",
        2: "Rabu",
        3: "Kamis",
        4: "Jumat",
        5: "Sabtu",
        6: "Minggu",
    }
    d = datetime.date.fromisoformat(date_str)
    return DAY_NAMES[d.weekday()]


def build_digest() -> str:
    from bot.db import get_client

    db = get_client()
    today_str = datetime.date.today().isoformat()
    yesterday_str = _get_yesterday()
    day_name = _day_name_bahasa(today_str)

    lines = [f"Selamat pagi! {day_name}, {today_str}"]
    lines.append("")

    # --- yesterday's sales summary ---
    sales_result = db.table("sales").select("quantity").eq("sale_date", yesterday_str).execute()
    sales_rows = sales_result.data or []
    total_qty = sum(r["quantity"] for r in sales_rows)
    total_txn = len(sales_rows)

    if total_txn == 0:
        lines.append(f"Kemarin ({yesterday_str}): belum ada penjualan tercatat.")
    else:
        lines.append(f"Kemarin ({yesterday_str}):")
        lines.append(f"  {total_txn} baris penjualan, total {total_qty:g} unit")

    lines.append("")

    # --- restock and fresh order sections ---
    restock_lines, fresh_lines = _build_inventory_section(db, today_str)

    if restock_lines:
        lines.append("PERLU RESTOCK (stok di bawah batas aman):")
        lines.extend(restock_lines)
        lines.append("")

    if fresh_lines:
        lines.append("BELANJA HARI INI (barang segar):")
        lines.extend(fresh_lines)
        lines.append("")

    if not restock_lines and not fresh_lines:
        lines.append("Stok semua barang masih aman.")
        lines.append("")

    # --- kasbon reminders ---
    kasbon_lines = _kasbon_reminders(db, today_str)
    if kasbon_lines:
        lines.append("KASBON (tagihan belum lunas):")
        lines.extend(kasbon_lines)
        lines.append("")

    lines.append("Semangat berjualan hari ini!")

    return "\n".join(lines)


def _build_inventory_section(db, today_str: str) -> tuple[list[str], list[str]]:
    """
    Return (restock_alert_lines, fresh_order_lines).

    Reads from restock_cache if available, falls back to simple
    3× daily demand threshold if the cache is empty.
    """
    # latest stock level per SKU
    stock_result = db.table("stock_log").select("sku_id, quantity, logged_at").execute()
    stock_rows = stock_result.data or []

    latest_stock: dict[int, float] = {}
    latest_ts: dict[int, str] = {}
    for row in stock_rows:
        sku_id = row["sku_id"]
        if sku_id not in latest_ts or row["logged_at"] > latest_ts[sku_id]:
            latest_ts[sku_id] = row["logged_at"]
            latest_stock[sku_id] = row["quantity"]

    # SKU metadata
    sku_result = (
        db.table("skus").select("sku_id, name, unit, is_perishable").eq("is_active", True).execute()
    )
    sku_map: dict[int, dict] = {r["sku_id"]: r for r in (sku_result.data or [])}

    # try to read from nightly cache first
    cache_result = (
        db.table("restock_cache")
        .select("sku_id, rop, order_qty, is_perishable, daily_rate")
        .eq("cache_date", today_str)
        .execute()
    )
    cache_rows = cache_result.data or []

    if cache_rows:
        return _from_cache(cache_rows, latest_stock, sku_map)
    else:
        return _fallback_alerts(db, latest_stock, sku_map)


def _from_cache(
    cache_rows: list[dict],
    latest_stock: dict[int, float],
    sku_map: dict[int, dict],
) -> tuple[list[str], list[str]]:
    """Use the nightly recompute cache to build alert lines."""
    restock_lines = []
    fresh_lines = []

    for row in cache_rows:
        sku_id = row["sku_id"]
        sku = sku_map.get(sku_id)
        if not sku:
            continue

        unit = sku["unit"]
        name = sku["name"]

        if row["is_perishable"]:
            # always show the daily buy quantity for fresh goods
            qty = row["order_qty"]
            if qty and qty > 0:
                fresh_lines.append(f"  • {name} — beli {qty:g} {unit}")
        else:
            # flag dry goods whose stock has fallen to or below the ROP
            rop = row["rop"]
            stock = latest_stock.get(sku_id)
            if rop is not None and stock is not None and stock <= rop:
                order_qty = row["order_qty"]
                restock_lines.append(
                    f"  • {name} — sisa {stock:g} {unit}"
                    f" (batas aman: {rop:g}, pesan: {order_qty:g} {unit})"
                )

    # sort alphabetically so the message is stable
    restock_lines.sort()
    fresh_lines.sort()

    return restock_lines[:10], fresh_lines[:10]


def _fallback_alerts(
    db,
    latest_stock: dict[int, float],
    sku_map: dict[int, dict],
) -> tuple[list[str], list[str]]:
    """
    Fallback used when the nightly cache is empty (cold start / first day).
    Uses 3× daily demand as the low-stock threshold.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    sales_result = db.table("sales").select("sku_id, quantity").gte("sale_date", cutoff).execute()
    demand_sum: dict[int, float] = {}
    for row in sales_result.data or []:
        sku_id = row["sku_id"]
        demand_sum[sku_id] = demand_sum.get(sku_id, 0.0) + row["quantity"]
    avg_daily: dict[int, float] = {sid: total / 30.0 for sid, total in demand_sum.items()}

    restock_lines = []
    fresh_lines = []

    for sku_id, stock in latest_stock.items():
        sku = sku_map.get(sku_id)
        if not sku:
            continue
        threshold = avg_daily.get(sku_id, 0.0) * 3
        if threshold > 0 and stock < threshold:
            name = sku["name"]
            unit = sku["unit"]
            if sku["is_perishable"]:
                order_qty = round(avg_daily.get(sku_id, 1.0))
                fresh_lines.append(f"  • {name} — beli ~{order_qty:g} {unit} (estimasi)")
            else:
                restock_lines.append(f"  • {name} — sisa {stock:g} {unit} (perlu restock)")

    return restock_lines[:10], fresh_lines[:10]


def _kasbon_reminders(db, today_str: str) -> list[str]:
    """
    Build kasbon reminder lines from the credit_cache and repayment_predictions.

    Ordering priority:
        1. Debts with low p30 (≤0.30) and long overdue — highest risk, show first.
        2. Otherwise, longest days_since_borrow first.

    Falls back to a direct ledger query if the cache is empty.
    """
    cache_rows = (
        db.table("credit_cache")
        .select("customer_id, band, outstanding, days_since_borrow")
        .eq("cache_date", today_str)
        .gt("outstanding", 0)
        .order("days_since_borrow", desc=True)
        .limit(8)
        .execute()
        .data
        or []
    )

    if not cache_rows:
        return _kasbon_reminders_fallback(db)

    customers = {
        r["customer_id"]: r
        for r in (
            db.table("customers")
            .select("customer_id, local_code, initials, display_name")
            .execute()
            .data
            or []
        )
    }

    # load p30 predictions for open debts — keyed by customer_id (min p30 per customer)
    pred_rows = (
        db.table("repayment_predictions")
        .select("ledger_id, p30")
        .eq("cache_date", today_str)
        .execute()
        .data
        or []
    )
    # join through kasbon_ledger to get customer_id
    if pred_rows:
        ledger_ids = [r["ledger_id"] for r in pred_rows]
        ledger_meta = (
            db.table("kasbon_ledger")
            .select("ledger_id, customer_id")
            .in_("ledger_id", ledger_ids)
            .execute()
            .data
            or []
        )
        ledger_cid = {r["ledger_id"]: r["customer_id"] for r in ledger_meta}
        # take the minimum p30 across all open debts per customer (most pessimistic)
        p30_by_customer: dict[int, float] = {}
        for pr in pred_rows:
            cid = ledger_cid.get(pr["ledger_id"])
            if cid is not None:
                current = p30_by_customer.get(cid, 1.0)
                p30_by_customer[cid] = min(current, float(pr["p30"]))
    else:
        p30_by_customer = {}

    BAND_LABEL = {"hijau": "[Hijau]", "kuning": "[Kuning]", "merah": "[MERAH]"}

    lines = []
    for row in cache_rows:
        cid = row["customer_id"]
        cust = customers.get(cid, {})
        name = cust.get("display_name") or cust.get("initials", f"ID-{cid}")
        band = row["band"]
        owed = row["outstanding"]
        days = row["days_since_borrow"]
        label = BAND_LABEL.get(band, "")
        flag = " ⚠" if days and days > 14 else ""

        # add p30 annotation when model has a pessimistic read
        p30 = p30_by_customer.get(cid)
        p30_note = f" [p30: {p30:.0%}]" if p30 is not None and p30 <= 0.30 else ""

        lines.append(f"  • {name} {label} — Rp{owed:,.0f} ({days} hari){flag}{p30_note}")

    return lines


def _kasbon_reminders_fallback(db) -> list[str]:
    """Direct ledger query fallback when credit_cache has no rows for today."""
    open_debts = (
        db.table("kasbon_ledger")
        .select("customer_id, amount, borrowed_at")
        .eq("is_cleared", False)
        .execute()
        .data
        or []
    )
    if not open_debts:
        return []

    customers = {
        r["customer_id"]: r
        for r in (
            db.table("customers")
            .select("customer_id, local_code, initials, display_name")
            .execute()
            .data
            or []
        )
    }

    by_customer: dict[int, dict] = {}
    for debt in open_debts:
        cid = debt["customer_id"]
        if cid not in by_customer:
            by_customer[cid] = {"total": 0.0, "oldest": debt["borrowed_at"][:10]}
        by_customer[cid]["total"] += float(debt["amount"])
        if debt["borrowed_at"][:10] < by_customer[cid]["oldest"]:
            by_customer[cid]["oldest"] = debt["borrowed_at"][:10]

    today = datetime.date.today()
    lines = []
    for cid, info in sorted(by_customer.items(), key=lambda x: x[1]["oldest"]):
        cust = customers.get(cid, {})
        name = cust.get("display_name") or cust.get("initials", f"ID-{cid}")
        days = (today - datetime.date.fromisoformat(info["oldest"])).days
        flag = " ⚠" if days > 14 else ""
        lines.append(f"  • {name} — Rp{info['total']:,.0f} ({days} hari){flag}")

    return lines[:8]


async def run() -> None:
    chat_id = os.environ.get("MERCHANT_CHAT_ID", "")
    if not chat_id:
        print("ERROR: MERCHANT_CHAT_ID is not set.")
        sys.exit(1)

    from bot.sender import send_message

    digest = build_digest()
    print("Sending morning digest:")
    print(digest)
    await send_message(chat_id, digest)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(run())
