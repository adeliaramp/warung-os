"""
Inventory policy layer, routed by demand class and perishability flag.

Dry / packaged goods  -> reorder point (ROP) policy
    ROP = forecast_over_lead_time + safety_stock
    safety_stock = z * sigma_lead_time_demand
    z is set by the target service level (default 95% -> z ~= 1.65)

Perishable goods -> newsvendor order-up-to level
    critical_ratio = margin / (margin + cost)
    optimal_qty    = quantile(empirical_demand_dist, critical_ratio)
    This minimizes the expected total cost of overstocking (spoilage)
    and understocking (lost margin).
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def reorder_point(
    forecast_lead: float,
    sigma_lead: float,
    service_level: float = 0.95,
) -> float:
    """
    Return the reorder point for a dry/packaged good.

    Parameters
    ----------
    forecast_lead : expected demand over the supplier lead time (units)
    sigma_lead    : std dev of demand over the lead time (units)
    service_level : target fill rate (0-1), default 0.95

    The reorder point is the stock level at which a replenishment order
    should be placed so that the probability of a stockout during the
    lead time is at most (1 - service_level).
    """
    z = stats.norm.ppf(service_level)
    return forecast_lead + z * sigma_lead


def newsvendor_quantity(
    demand_samples: list[float],
    margin_per_unit: float,
    cost_per_unit: float,
) -> float:
    """
    Return the optimal order quantity for a perishable good (newsvendor model).

    Parameters
    ----------
    demand_samples  : historical daily demand observations (nonzero days)
    margin_per_unit : sell_price - cost_price (IDR)
    cost_per_unit   : cost_price (IDR), lost when stock spoils unsold

    The critical ratio is the probability of demand being at or below
    the order quantity that minimizes expected total cost. It equals
    margin / (margin + cost).

    The optimal quantity is the empirical quantile of historical demand
    at the critical ratio.
    """
    if not demand_samples or margin_per_unit <= 0:
        return 0.0

    cr = margin_per_unit / (margin_per_unit + cost_per_unit)
    return float(np.quantile(demand_samples, cr))


def newsvendor_cost_curve(
    demand_samples: list[float],
    margin_per_unit: float,
    cost_per_unit: float,
    qty_range: list[float] | None = None,
) -> dict:
    """
    Compute the expected cost curve across a range of order quantities.

    Returns a dict with:
        quantities      : list of order quantities evaluated
        expected_waste  : expected spoilage cost at each quantity
        expected_stockout: expected lost margin at each quantity
        total_cost      : sum of the two
        optimal_qty     : quantity that minimizes total_cost
        optimal_idx     : index of optimal_qty in quantities
    """
    demand_arr = np.array([d for d in demand_samples if not np.isnan(d) and d >= 0])
    if len(demand_arr) == 0:
        return {}

    if qty_range is None:
        max_qty = int(np.percentile(demand_arr, 99)) + 5
        qty_range = list(range(0, max_qty + 1))

    expected_waste = []
    expected_stockout = []

    for q in qty_range:
        # spoilage cost: units ordered but not sold * cost_per_unit
        waste = np.mean(np.maximum(q - demand_arr, 0)) * cost_per_unit
        # stockout cost: units demanded but not available * margin_per_unit
        lost = np.mean(np.maximum(demand_arr - q, 0)) * margin_per_unit
        expected_waste.append(waste)
        expected_stockout.append(lost)

    total = [w + s for w, s in zip(expected_waste, expected_stockout)]
    optimal_idx = int(np.argmin(total))

    return {
        "quantities": qty_range,
        "expected_waste": expected_waste,
        "expected_stockout": expected_stockout,
        "total_cost": total,
        "optimal_qty": qty_range[optimal_idx],
        "optimal_idx": optimal_idx,
    }


def compute_rop_policy(
    sku_id: int,
    sales: "pd.DataFrame",  # noqa: F821
    lead_time_days: int = 1,
    service_level: float = 0.95,
) -> dict:
    """
    Compute the reorder point policy parameters for one dry/packaged SKU.

    Returns dict with: rop, safety_stock, forecast_lead, sigma_lead
    """
    import pandas as pd

    from analytics.forecasting import forecast as do_forecast
    from analytics.classifier import compute_adi, compute_cv2, classify

    sku_sales = sales[sales["sku_id"] == sku_id]["quantity"].dropna()

    # daily demand rate via the appropriate forecasting method
    demand_class = classify(
        compute_adi(pd.Series(sku_sales.values)),
        compute_cv2(pd.Series(sku_sales.values)),
    )
    daily_rate = do_forecast(sku_sales.tolist(), demand_class)

    # demand over lead time
    forecast_lead = daily_rate * lead_time_days

    # std dev of demand over lead time (assume demand is iid across days)
    daily_std = sku_sales[sku_sales > 0].std() if len(sku_sales[sku_sales > 0]) > 1 else 1.0
    sigma_lead = daily_std * (lead_time_days**0.5)

    rop = reorder_point(forecast_lead, sigma_lead, service_level)

    return {
        "sku_id": sku_id,
        "demand_class": demand_class,
        "daily_rate": round(daily_rate, 2),
        "forecast_lead": round(forecast_lead, 2),
        "sigma_lead": round(sigma_lead, 2),
        "safety_stock": round(stats.norm.ppf(service_level) * sigma_lead, 2),
        "rop": round(rop, 1),
    }
