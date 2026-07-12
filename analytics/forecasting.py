"""
Demand forecasting methods, routed by demand class.

    smooth      -> exponential smoothing (single, alpha tunable)
    erratic     -> SBA (Syntetos-Boylan Approximation)
    intermittent-> Croston's method
    lumpy       -> SBA

All methods accept a list or array of historical daily demand values
and return a one-step-ahead forecast of daily demand rate.
"""

from __future__ import annotations

import numpy as np


def exponential_smoothing(demand: list[float], alpha: float = 0.2) -> float:
    """
    Single exponential smoothing.

    Appropriate for smooth demand (low intermittency, low variability).
    Returns a forecast of the next period's demand.

    alpha: smoothing parameter in (0, 1). Higher alpha reacts faster
    to recent demand but is noisier.
    """
    demand = [d for d in demand if not np.isnan(d)]
    if not demand:
        return 0.0
    forecast = demand[0]
    for actual in demand[1:]:
        forecast = alpha * actual + (1 - alpha) * forecast
    return max(forecast, 0.0)


def croston(demand: list[float], alpha: float = 0.1) -> float:
    """
    Croston's method for intermittent demand.

    Separates the demand process into two components updated only
    on nonzero demand periods:
        z: smoothed nonzero demand size
        p: smoothed inter-demand interval

    Demand rate estimate = z / p

    Appropriate for intermittent demand (ADI >= 1.32, CV² < 0.49).
    """
    demand = [d for d in demand if not np.isnan(d)]
    if not demand:
        return 0.0

    # initialize on the first nonzero observation
    z = None  # smoothed demand size
    p = None  # smoothed inter-demand interval
    q = 0  # periods since last nonzero demand

    for d in demand:
        q += 1
        if d > 0:
            if z is None:
                # first nonzero period: initialize both components
                z = d
                p = q
            else:
                z = alpha * d + (1 - alpha) * z
                p = alpha * q + (1 - alpha) * p
            q = 0

    if z is None or p is None or p == 0:
        return 0.0

    return z / p


def sba(demand: list[float], alpha: float = 0.1) -> float:
    """
    Syntetos-Boylan Approximation — bias-corrected Croston.

    Croston's method overestimates the mean demand rate by a factor
    of approximately 1 / (1 - alpha/2). SBA corrects for this:
        SBA rate = (1 - alpha/2) * Croston rate

    Appropriate for erratic and lumpy demand.
    """
    raw = croston(demand, alpha)
    correction = 1.0 - alpha / 2.0
    return correction * raw


def forecast(demand: list[float], demand_class: str, alpha: float = 0.1) -> float:
    """
    Route to the correct forecasting method by demand class.

    Returns daily demand rate estimate (units per day).
    """
    if demand_class == "smooth":
        return exponential_smoothing(demand, alpha=0.2)
    elif demand_class == "intermittent":
        return croston(demand, alpha=alpha)
    else:
        # erratic and lumpy both use SBA
        return sba(demand, alpha=alpha)
