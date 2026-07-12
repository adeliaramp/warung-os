"""
Nightly recompute job — runs via GitHub Actions cron at 23:00 WIB (16:00 UTC).

1. Fetches all sales and SKU data from Supabase.
2. Runs the restock recommendation engine (classifier + ROP + newsvendor).
3. Upserts one row per SKU into restock_cache for tomorrow's morning digest.
4. Fetches customers, kasbon ledger, repayments.
5. Runs the credit scorecard for all active customers.
6. Upserts one row per customer into credit_cache.
7. Fits the Cox repayment survival model on historical debts.
8. Predicts P(repaid within 30 days) for all open debts.
9. Upserts predictions into repayment_predictions.
"""

from __future__ import annotations

import datetime
import os
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run() -> None:
    from bot.db import get_client
    from analytics.restock import run_restock
    from analytics.credit import score_all_customers, suggest_credit_limit
    from analytics.survival import build_survival_dataset, fit_cox, predict_p30

    db = get_client()
    cache_date = datetime.date.today().isoformat()
    snapshot = pd.Timestamp(cache_date)

    print(f"Nightly recompute for {cache_date} ...")

    # -----------------------------------------------------------------------
    # Part 1: restock recommendations
    # -----------------------------------------------------------------------

    print("  Fetching SKUs ...")
    sku_rows = db.table("skus").select("*").eq("is_active", True).execute().data or []
    if not sku_rows:
        print("  No active SKUs. Skipping restock step.")
    else:
        skus = pd.DataFrame(sku_rows)

        print("  Fetching sales ...")
        sales_rows = db.table("sales").select("sku_id, quantity, sale_date").execute().data or []

        if not sales_rows:
            print("  No sales data. Skipping restock step.")
        else:
            sales = pd.DataFrame(sales_rows)
            print("  Running restock engine ...")
            recs = run_restock(sales, skus)
            print(f"  Got recommendations for {len(recs)} SKUs.")

            if not recs.empty:
                rows_to_upsert = []
                for _, row in recs.iterrows():
                    rows_to_upsert.append(
                        {
                            "sku_id": int(row["sku_id"]),
                            "cache_date": cache_date,
                            "demand_class": row["demand_class"],
                            "daily_rate": float(row["daily_rate"]),
                            "rop": float(row["rop"]) if row["rop"] is not None else None,
                            "order_qty": (
                                float(row["order_qty"]) if row["order_qty"] is not None else None
                            ),
                            "is_perishable": bool(row["is_perishable"]),
                        }
                    )
                db.table("restock_cache").upsert(
                    rows_to_upsert, on_conflict="sku_id,cache_date"
                ).execute()
                print(f"  Upserted {len(rows_to_upsert)} restock rows.")

    # -----------------------------------------------------------------------
    # Part 2: credit scoring
    # -----------------------------------------------------------------------

    print("  Fetching customers ...")
    customer_rows = db.table("customers").select("*").eq("is_active", True).execute().data or []

    if not customer_rows:
        print("  No active customers. Skipping credit step.")
    else:
        customers = pd.DataFrame(customer_rows)

        print("  Fetching kasbon ledger ...")
        ledger_rows = (
            db.table("kasbon_ledger")
            .select("ledger_id, customer_id, amount, borrowed_at, is_cleared")
            .execute()
            .data
            or []
        )
        ledger = (
            pd.DataFrame(ledger_rows)
            if ledger_rows
            else pd.DataFrame(
                columns=["ledger_id", "customer_id", "amount", "borrowed_at", "is_cleared"]
            )
        )
        if not ledger.empty:
            ledger["borrowed_at"] = pd.to_datetime(ledger["borrowed_at"])

        print("  Fetching repayments ...")
        repayment_rows = (
            db.table("kasbon_repayments")
            .select("repayment_id, ledger_id, amount, repaid_at")
            .execute()
            .data
            or []
        )
        repayments = (
            pd.DataFrame(repayment_rows)
            if repayment_rows
            else pd.DataFrame(columns=["repayment_id", "ledger_id", "amount", "repaid_at"])
        )
        if not repayments.empty:
            repayments["repaid_at"] = pd.to_datetime(repayments["repaid_at"])

        print("  Running credit scorecard ...")
        scores = score_all_customers(customers, ledger, repayments, snapshot)
        print(f"  Scored {len(scores)} customers.")

        # estimate working capital from recent sales
        estimated_wc = _estimate_working_capital(db)
        active_count = len(customers)

        # compute outstanding per customer
        if not ledger.empty:
            open_ledger = ledger[~ledger["is_cleared"]]
            outstanding_map: dict[int, float] = (
                open_ledger.groupby("customer_id")["amount"].sum().to_dict()
            )
        else:
            outstanding_map = {}

        # days since most recent open debt per customer
        if not ledger.empty:
            open_ledger = ledger[~ledger["is_cleared"]]
            if not open_ledger.empty:
                latest_borrow = open_ledger.groupby("customer_id")["borrowed_at"].max()
                today = pd.Timestamp(cache_date)
                days_since_map: dict[int, int] = {
                    cid: (today - ts).days for cid, ts in latest_borrow.items()
                }
            else:
                days_since_map = {}
        else:
            days_since_map = {}

        credit_rows = []
        for _, score_row in scores.iterrows():
            cid = int(score_row["customer_id"])
            limit = suggest_credit_limit(score_row.to_dict(), ledger, estimated_wc, active_count)
            credit_rows.append(
                {
                    "customer_id": cid,
                    "cache_date": cache_date,
                    "score": int(score_row["score"]) if score_row["score"] is not None else None,
                    "band": str(score_row["band"]),
                    "outstanding": float(outstanding_map.get(cid, 0.0)),
                    "suggested_limit": float(limit),
                    "days_since_borrow": days_since_map.get(cid),
                }
            )

        db.table("credit_cache").upsert(credit_rows, on_conflict="customer_id,cache_date").execute()
        print(f"  Upserted {len(credit_rows)} credit rows.")

        # -------------------------------------------------------------------
        # Part 3: repayment survival predictions
        # -------------------------------------------------------------------

        print("  Building survival dataset ...")
        survival_df = build_survival_dataset(ledger, repayments, customers, snapshot)

        if survival_df.empty:
            print("  No survival data. Skipping repayment predictions.")
        else:
            open_ledger = ledger[~ledger["is_cleared"]]

            if open_ledger.empty:
                print("  No open debts. Skipping repayment predictions.")
            else:
                print("  Fitting Cox model ...")
                cox_model = fit_cox(survival_df)
                if cox_model is None:
                    print("  Fewer than 20 closed debts — using KM fallback.")
                else:
                    print("  Cox model fitted.")

                # band_map from the scores we already computed
                band_map: dict[int, str] = {
                    int(r["customer_id"]): str(r["band"]) for r in credit_rows
                }

                predictions = predict_p30(survival_df, open_ledger, cox_model, band_map)
                print(f"  Predicted p30 for {len(predictions)} open debts.")

                if not predictions.empty:
                    pred_rows = []
                    for _, pred in predictions.iterrows():
                        pred_rows.append(
                            {
                                "ledger_id": int(pred["ledger_id"]),
                                "cache_date": cache_date,
                                "p30": float(pred["p30"]),
                                "model_type": str(pred["model_type"]),
                            }
                        )
                    db.table("repayment_predictions").upsert(
                        pred_rows, on_conflict="ledger_id,cache_date"
                    ).execute()
                    print(f"  Upserted {len(pred_rows)} repayment prediction rows.")

    print("Done.")


def _estimate_working_capital(db) -> float:
    """
    Estimate the shop's working capital as 30 days of average daily revenue.
    Uses the last 90 days of sales data.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    rows = (
        db.table("sales")
        .select("sku_id, quantity, sale_date")
        .gte("sale_date", cutoff)
        .execute()
        .data
        or []
    )
    if not rows:
        return 1_000_000.0  # conservative fallback: Rp 1 juta

    sku_prices = {
        r["sku_id"]: r["sell_price"]
        for r in (db.table("skus").select("sku_id, sell_price").execute().data or [])
        if r["sell_price"]
    }

    total_revenue = sum(float(r["quantity"]) * float(sku_prices.get(r["sku_id"], 0)) for r in rows)
    daily_avg = total_revenue / 90.0
    return daily_avg * 30.0


if __name__ == "__main__":
    run()
