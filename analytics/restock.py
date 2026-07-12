"""
Restock recommendation engine — orchestrates the classifier and inventory
policy modules to produce one recommendation per SKU per day.

Output per SKU:
    demand_class  : smooth / erratic / intermittent / lumpy
    daily_rate    : forecast demand rate (units/day)
    rop           : reorder point (dry goods only, None for perishables)
    order_qty     : recommended order quantity for today
    is_perishable : True if the SKU should follow the newsvendor policy

This module is pure-pandas — it does not touch the database.
The nightly_recompute job handles DB reads/writes and calls run_restock().
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.classifier import compute_adi, compute_cv2, classify
from analytics.forecasting import forecast
from analytics.inventory import reorder_point, newsvendor_quantity

# Lead time assumption: supplier delivers next day
LEAD_TIME_DAYS = 1

# Target service level for safety stock on dry goods
SERVICE_LEVEL = 0.95

# Replenishment order: 10 days of demand (for dry goods that need restock)
REPLENISHMENT_DAYS = 10

# Minimum days of sales history required to make a recommendation
MIN_HISTORY_DAYS = 14


def run_restock(
    sales: pd.DataFrame,
    skus: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute restock recommendations for all SKUs from historical sales data.

    Parameters
    ----------
    sales : DataFrame with columns [sku_id, quantity, sale_date]
    skus  : DataFrame with columns [sku_id, name, unit, category,
                                     is_perishable, cost_price, sell_price]

    Returns
    -------
    DataFrame with columns:
        sku_id, demand_class, daily_rate, rop, order_qty, is_perishable
    """
    sales = sales.copy()
    sales["sale_date"] = pd.to_datetime(sales["sale_date"])

    # need at least MIN_HISTORY_DAYS of data to make a recommendation
    cutoff = sales["sale_date"].max() - pd.Timedelta(days=MIN_HISTORY_DAYS)

    # build a date-indexed daily demand series for every SKU
    all_dates = pd.date_range(sales["sale_date"].min(), sales["sale_date"].max(), freq="D")
    pivot = (
        sales.pivot_table(
            index="sale_date",
            columns="sku_id",
            values="quantity",
            aggfunc="sum",
        )
        .reindex(all_dates)
        .fillna(0)
    )

    rows = []
    for _, sku in skus.iterrows():
        sku_id = sku["sku_id"]
        if sku_id not in pivot.columns:
            continue

        col = pivot[sku_id]

        # only use recent history so the forecast reflects current conditions
        recent = col[col.index >= cutoff]
        if len(recent) < MIN_HISTORY_DAYS:
            continue

        demand_list = recent.tolist()
        nonzero = [d for d in demand_list if d > 0]
        if not nonzero:
            continue

        # classify
        adi = compute_adi(recent)
        cv2 = compute_cv2(recent)
        demand_class = classify(adi, cv2)

        # daily demand rate
        daily_rate = forecast(demand_list, demand_class)

        is_perishable = bool(sku["is_perishable"])

        if is_perishable:
            # newsvendor: use the nonzero demand distribution
            cost = float(sku["cost_price"] or 0)
            sell = float(sku["sell_price"] or 0)
            margin = sell - cost
            if margin > 0 and cost > 0:
                opt_qty = newsvendor_quantity(nonzero, margin, cost)
            else:
                # fallback: median of nonzero days
                opt_qty = float(np.median(nonzero))
            rop = None
            order_qty = round(opt_qty, 1)
        else:
            # ROP policy
            nonzero_series = recent[recent > 0]
            sigma_day = float(nonzero_series.std()) if len(nonzero_series) > 1 else 1.0
            sigma_lead = sigma_day * (LEAD_TIME_DAYS**0.5)
            forecast_lead = daily_rate * LEAD_TIME_DAYS
            rop = reorder_point(forecast_lead, sigma_lead, SERVICE_LEVEL)
            # standard replenishment quantity
            order_qty = round(daily_rate * REPLENISHMENT_DAYS, 1)

        rows.append(
            {
                "sku_id": int(sku_id),
                "demand_class": demand_class,
                "daily_rate": round(daily_rate, 3),
                "rop": round(rop, 2) if rop is not None else None,
                "order_qty": order_qty,
                "is_perishable": is_perishable,
            }
        )

    return pd.DataFrame(rows)
