"""
Route parsed intents to the appropriate Supabase writes and Telegram replies.

Each handler receives the intent dict, the Telegram chat_id, and the
Supabase client. It writes to the DB and returns a reply string in Bahasa.
"""

from __future__ import annotations

import datetime

from bot.customer_lookup import customer_display, find_customer
from bot.db import get_client
from bot.sku_lookup import find_sku


def _today() -> str:
    return datetime.date.today().isoformat()


def handle_sale(intent: dict, chat_id: int | str) -> str:
    """Write a sale record and return a confirmation reply."""
    sku_raw: str = intent.get("sku_raw", "")
    qty: float = intent.get("qty", 1.0)

    sku = find_sku(sku_raw)
    if sku is None:
        return (
            f"Maaf, saya tidak menemukan barang '{sku_raw}' di katalog.\n"
            "Cek ejaan atau ketik /katalog untuk lihat daftar barang."
        )

    get_client().table("sales").insert(
        {
            "sku_id": sku["sku_id"],
            "quantity": qty,
            "sale_date": _today(),
            "source": "telegram",
        }
    ).execute()

    unit = sku.get("unit", "")
    return f"Tercatat: {sku['name']} {qty:g} {unit} terjual hari ini."


def handle_stock(intent: dict, chat_id: int | str) -> str:
    """Write a stock log entry and return a confirmation reply."""
    sku_raw: str = intent.get("sku_raw", "")
    qty: float = intent.get("qty", 0.0)

    if qty is None:
        return "Tolong tulis jumlah stok. Contoh: stok tahu 20"

    sku = find_sku(sku_raw)
    if sku is None:
        return (
            f"Maaf, saya tidak menemukan barang '{sku_raw}' di katalog.\n"
            "Cek ejaan atau ketik /katalog untuk lihat daftar barang."
        )

    get_client().table("stock_log").insert(
        {
            "sku_id": sku["sku_id"],
            "quantity": qty,
            "source": "telegram",
        }
    ).execute()

    unit = sku.get("unit", "")
    return f"Stok {sku['name']} dicatat: {qty:g} {unit}."


def handle_kasbon(intent: dict, chat_id: int | str) -> str:
    """Record a kasbon (credit borrow) event and return a confirmation reply."""
    customer_raw: str = intent.get("customer_raw", "")
    amount: float = intent.get("amount", 0.0)

    customer = find_customer(customer_raw)
    if customer is None:
        return (
            f"Pelanggan '{customer_raw}' tidak ditemukan.\n"
            "Ketik /pelanggan untuk lihat daftar pelanggan."
        )

    if not amount or amount <= 0:
        return "Tolong tulis jumlah kasbon. Contoh: kasbon bu sri 20rb"

    db = get_client()

    # check consent before writing
    consent = (
        db.table("customers")
        .select("consent_at")
        .eq("customer_id", customer["customer_id"])
        .single()
        .execute()
        .data
        or {}
    )
    if not consent.get("consent_at"):
        return (
            f"Catatan kasbon untuk {customer_display(customer)} belum bisa disimpan "
            "karena persetujuan (consent) belum dicatat.\n"
            "Minta pelanggan menyetujui dulu, lalu ketik: /setujui [kode pelanggan]"
        )

    db.table("kasbon_ledger").insert(
        {
            "customer_id": customer["customer_id"],
            "amount": amount,
            "is_cleared": False,
        }
    ).execute()

    name = customer_display(customer)
    return f"Kasbon dicatat: {name} pinjam Rp{amount:,.0f}."


def handle_repayment(intent: dict, chat_id: int | str) -> str:
    """Record a kasbon repayment and return a confirmation reply."""
    customer_raw: str = intent.get("customer_raw", "")
    amount: float | None = intent.get("amount")  # None means full settlement

    customer = find_customer(customer_raw)
    if customer is None:
        return (
            f"Pelanggan '{customer_raw}' tidak ditemukan.\n"
            "Ketik /pelanggan untuk lihat daftar pelanggan."
        )

    db = get_client()
    customer_id = customer["customer_id"]
    name = customer_display(customer)

    # find open debts ordered oldest first
    open_debts = (
        db.table("kasbon_ledger")
        .select("ledger_id, amount")
        .eq("customer_id", customer_id)
        .eq("is_cleared", False)
        .order("borrowed_at")
        .execute()
        .data
        or []
    )

    if not open_debts:
        return f"{name} tidak punya kasbon yang belum lunas."

    # compute total outstanding
    total_outstanding = sum(float(d["amount"]) for d in open_debts)

    if amount is None:
        # full settlement: clear all open debts
        payment = total_outstanding
    else:
        payment = float(amount)

    # apply payment to debts oldest-first
    remaining_payment = payment
    for debt in open_debts:
        if remaining_payment <= 0:
            break
        debt_amount = float(debt["amount"])

        # sum previous repayments for this debt
        prev_repaid = (
            db.table("kasbon_repayments")
            .select("amount")
            .eq("ledger_id", debt["ledger_id"])
            .execute()
            .data
            or []
        )
        already_paid = sum(float(r["amount"]) for r in prev_repaid)
        still_owed = debt_amount - already_paid

        if still_owed <= 0:
            continue

        pay_this_debt = min(remaining_payment, still_owed)

        db.table("kasbon_repayments").insert(
            {"ledger_id": debt["ledger_id"], "amount": pay_this_debt}
        ).execute()

        remaining_payment -= pay_this_debt

        # mark cleared if fully paid
        if already_paid + pay_this_debt >= debt_amount:
            db.table("kasbon_ledger").update({"is_cleared": True}).eq(
                "ledger_id", debt["ledger_id"]
            ).execute()

    new_outstanding = max(0.0, total_outstanding - payment)

    if new_outstanding == 0:
        return f"Lunas! {name} sudah melunasi semua kasbon. Terima kasih!"

    return (
        f"Pembayaran Rp{payment:,.0f} dari {name} dicatat.\n"
        f"Sisa kasbon: Rp{new_outstanding:,.0f}."
    )


def handle_command(intent: dict, chat_id: int | str) -> str:
    """Handle slash commands."""
    name = intent.get("name", "")

    if name in ("start", "mulai", "halo"):
        return (
            "Halo! Saya asisten warung Anda.\n\n"
            "Cara pakai:\n"
            "• Catat penjualan: ketik nama barang lalu jumlah\n"
            "  Contoh: indomie 3\n\n"
            "• Catat stok: ketik 'stok' lalu nama barang dan jumlah\n"
            "  Contoh: stok tahu 20\n\n"
            "• Lihat daftar barang: /katalog\n"
            "• Lihat ringkasan hari ini: /status"
        )

    if name in ("help", "bantuan"):
        return (
            "Perintah yang tersedia:\n"
            "/mulai — cara penggunaan\n"
            "/status — ringkasan penjualan hari ini\n"
            "/katalog — daftar barang yang terdaftar"
        )

    if name == "status":
        return _status_reply()

    if name == "katalog":
        return _katalog_reply()

    if name in ("pelanggan", "customer"):
        return _pelanggan_reply()

    if name in ("kasbon", "hutang", "piutang"):
        return _kasbon_summary_reply()

    return f"Perintah '/{name}' belum tersedia. Ketik /bantuan untuk bantuan."


def _status_reply() -> str:
    """Quick sales summary for today."""
    today = _today()
    result = get_client().table("sales").select("quantity, sku_id").eq("sale_date", today).execute()
    rows = result.data or []
    total_items = sum(r["quantity"] for r in rows)
    transaction_count = len(rows)

    if transaction_count == 0:
        return f"Hari ini ({today}) belum ada penjualan yang tercatat."

    return (
        f"Ringkasan hari ini ({today}):\n"
        f"• {transaction_count} baris penjualan tercatat\n"
        f"• Total {total_items:g} unit terjual"
    )


def _katalog_reply() -> str:
    """Return a short list of active SKUs grouped by category."""
    result = (
        get_client()
        .table("skus")
        .select("name, unit, category")
        .eq("is_active", True)
        .order("category")
        .execute()
    )
    rows = result.data or []
    if not rows:
        return "Katalog masih kosong."

    grouped: dict[str, list[str]] = {}
    for row in rows:
        cat = row["category"]
        grouped.setdefault(cat, []).append(f"{row['name']} ({row['unit']})")

    lines = ["Daftar barang:"]
    for cat, items in sorted(grouped.items()):
        lines.append(f"\n{cat.upper()}")
        for item in items[:10]:  # cap at 10 per category to keep message short
            lines.append(f"  • {item}")
        if len(items) > 10:
            lines.append(f"  ... dan {len(items) - 10} barang lainnya")

    return "\n".join(lines)


def _pelanggan_reply() -> str:
    """List active customers with their current outstanding kasbon."""
    db = get_client()

    customers = db.table("customers").select("*").eq("is_active", True).execute().data or []
    if not customers:
        return "Belum ada pelanggan kasbon yang terdaftar."

    # outstanding per customer
    open_debts = (
        db.table("kasbon_ledger")
        .select("customer_id, amount")
        .eq("is_cleared", False)
        .execute()
        .data
        or []
    )
    outstanding: dict[int, float] = {}
    for row in open_debts:
        cid = row["customer_id"]
        outstanding[cid] = outstanding.get(cid, 0.0) + float(row["amount"])

    lines = ["Daftar pelanggan kasbon:"]
    for cust in sorted(customers, key=lambda c: c["local_code"]):
        cid = cust["customer_id"]
        name = cust.get("display_name") or cust["initials"]
        code = cust["local_code"]
        owed = outstanding.get(cid, 0.0)
        if owed > 0:
            lines.append(f"  • {name} ({code}) — hutang Rp{owed:,.0f}")
        else:
            lines.append(f"  • {name} ({code}) — lunas")

    total = sum(outstanding.values())
    if total > 0:
        lines.append(f"\nTotal piutang: Rp{total:,.0f}")

    return "\n".join(lines)


def _kasbon_summary_reply() -> str:
    """Show outstanding kasbon sorted by oldest open debt."""
    db = get_client()

    open_debts = (
        db.table("kasbon_ledger")
        .select("customer_id, amount, borrowed_at")
        .eq("is_cleared", False)
        .order("borrowed_at")
        .execute()
        .data
        or []
    )

    if not open_debts:
        return "Tidak ada kasbon yang belum lunas. Bagus!"

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

    # group by customer
    by_customer: dict[int, list[dict]] = {}
    for debt in open_debts:
        cid = debt["customer_id"]
        by_customer.setdefault(cid, []).append(debt)

    import datetime

    today = datetime.date.today()
    lines = ["Kasbon belum lunas:"]
    total = 0.0

    for cid, debts in by_customer.items():
        cust = customers.get(cid, {})
        name = cust.get("display_name") or cust.get("initials", f"ID-{cid}")
        total_owed = sum(float(d["amount"]) for d in debts)
        oldest = min(d["borrowed_at"][:10] for d in debts)
        days_open = (today - datetime.date.fromisoformat(oldest)).days
        flag = " ⚠" if days_open > 14 else ""
        lines.append(f"  • {name} — Rp{total_owed:,.0f} ({days_open} hari){flag}")
        total += total_owed

    lines.append(f"\nTotal: Rp{total:,.0f}")
    return "\n".join(lines)


def dispatch(intent: dict, chat_id: int | str) -> str:
    """Route an intent to the correct handler and return the reply text."""
    intent_type = intent.get("type", "unknown")

    if intent_type == "sale":
        return handle_sale(intent, chat_id)
    if intent_type == "stock":
        return handle_stock(intent, chat_id)
    if intent_type == "kasbon":
        return handle_kasbon(intent, chat_id)
    if intent_type == "repayment":
        return handle_repayment(intent, chat_id)
    if intent_type == "command":
        return handle_command(intent, chat_id)

    # unknown or unhandled
    raw = intent.get("raw", "")
    if raw:
        return (
            f"Saya belum mengerti '{raw}'.\n"
            "Contoh: indomie 3 (catat penjualan) atau stok tahu 20 (catat stok)."
        )
    return "Maaf, saya tidak mengerti. Ketik /bantuan untuk panduan."
