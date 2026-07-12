"""
Credit scorecard and repayment prediction.

Behavioral scorecard:
    Points table over five observable dimensions from first-party history.
    Score in [0, 100] -> band: Hijau >= 70, Kuning 50-69, Merah < 50.

Credit limit suggestion:
    Per-customer limit = min(
        capacity_from_repayment_history,
        shop_credit_budget / active_customer_count
    )

Survival model (M5):
    Kaplan-Meier curves per band + Cox regression on amount, tenure,
    days_since_payday. Implemented in M5.
"""

import pandas as pd

# ---------------------------------------------------------------------------
# Scorecard weights
# ---------------------------------------------------------------------------

SCORECARD_WEIGHTS: dict[str, dict] = {
    "on_time_ratio": {
        # fraction of debts fully repaid within the expected window
        "breakpoints": [0.9, 0.7, 0.5, 0.0],
        "points": [30, 20, 10, 0],
    },
    "avg_days_late": {
        # mean days to repayment past 14-day expected window
        "breakpoints": [0, 3, 7, 14],
        "points": [20, 15, 5, 0],
    },
    "tenure_months": {
        # how long the customer has borrowed from this shop
        "breakpoints": [12, 6, 3, 0],
        "points": [20, 15, 5, 0],
    },
    "utilization": {
        # current outstanding / historical max outstanding (0-1)
        "breakpoints": [0.3, 0.5, 0.8, 1.0],
        "points": [20, 10, 5, 0],
    },
    "borrow_frequency": {
        # average borrows per month
        "breakpoints": [1, 2, 4, 99],
        "points": [10, 8, 5, 0],
    },
}

BAND_THRESHOLDS = {"hijau": 70, "kuning": 50}

# expected repayment window for on-time calculation (days)
ONTIME_WINDOW_DAYS = 14

# fraction of estimated working capital to allocate as total credit budget
CREDIT_BUDGET_FRACTION = 0.15


def _lookup_points(value: float, breakpoints: list[float], points: list[int]) -> int:
    """
    Return the points for a value given a breakpoints/points table.

    breakpoints are applied as >= thresholds in descending order.
    The first threshold the value satisfies earns those points.
    """
    for threshold, pts in zip(breakpoints, points):
        if value >= threshold:
            return pts
    return 0


def score_customer(
    customer_id: int,
    ledger: pd.DataFrame,
    repayments: pd.DataFrame,
    snapshot_date: pd.Timestamp,
    tenure_start: pd.Timestamp,
) -> dict:
    """
    Compute the behavioral scorecard for one customer.

    Parameters
    ----------
    customer_id   : the customer to score
    ledger        : kasbon_ledger DataFrame
    repayments    : kasbon_repayments DataFrame
    snapshot_date : the date as of which the score is computed
    tenure_start  : the date the customer first became a kasbon customer

    Returns dict with: customer_id, score, band, component breakdown
    """
    cust_ledger = ledger[
        (ledger["customer_id"] == customer_id) & (ledger["borrowed_at"] <= snapshot_date)
    ].copy()

    if cust_ledger.empty:
        # no history: return a thin-file placeholder
        return {
            "customer_id": customer_id,
            "score": None,
            "band": "thin_file",
            "on_time_ratio": None,
            "avg_days_late": None,
            "tenure_months": None,
            "utilization": None,
            "borrow_frequency": None,
            "points_breakdown": {},
        }

    # --- on_time_ratio and avg_days_late ---
    # use only cleared debts to avoid penalizing still-open ones
    cleared = cust_ledger[cust_ledger["is_cleared"]].copy()

    if cleared.empty:
        on_time_ratio = 0.0
        avg_days_late = float("inf")
    else:
        cleared_ids = cleared["ledger_id"].tolist()
        cust_repays = repayments[repayments["ledger_id"].isin(cleared_ids)]

        # last repayment date per debt
        last_repay = cust_repays.groupby("ledger_id")["repaid_at"].max()
        cleared = cleared.set_index("ledger_id")
        cleared["last_repaid_at"] = last_repay
        cleared["days_to_clear"] = (cleared["last_repaid_at"] - cleared["borrowed_at"]).dt.days

        on_time = (cleared["days_to_clear"] <= ONTIME_WINDOW_DAYS).mean()
        on_time_ratio = float(on_time)

        # days late = max(0, days_to_clear - ONTIME_WINDOW_DAYS)
        days_late = (cleared["days_to_clear"] - ONTIME_WINDOW_DAYS).clip(lower=0)
        avg_days_late = float(days_late.mean())

    # --- tenure ---
    tenure_months = (snapshot_date - tenure_start).days / 30.44
    tenure_months = max(0.0, tenure_months)

    # --- utilization ---
    outstanding = cust_ledger[~cust_ledger["is_cleared"]]["amount"].sum()
    hist_max_outstanding = cust_ledger["amount"].sum()
    utilization = float(outstanding / hist_max_outstanding) if hist_max_outstanding > 0 else 0.0
    utilization = min(utilization, 1.0)

    # --- borrow frequency ---
    months_active = max(tenure_months, 1.0)
    borrow_freq = len(cust_ledger) / months_active

    # --- score ---
    breakdown = {}
    total_points = 0

    for dimension, cfg in SCORECARD_WEIGHTS.items():
        value_map = {
            "on_time_ratio": on_time_ratio,
            "avg_days_late": avg_days_late if avg_days_late != float("inf") else 99,
            "tenure_months": tenure_months,
            "utilization": utilization,
            "borrow_frequency": borrow_freq,
        }
        pts = _lookup_points(value_map[dimension], cfg["breakpoints"], cfg["points"])
        breakdown[dimension] = pts
        total_points += pts

    band = band_from_score(total_points)

    return {
        "customer_id": customer_id,
        "score": total_points,
        "band": band,
        "on_time_ratio": round(on_time_ratio, 3),
        "avg_days_late": round(avg_days_late, 1) if avg_days_late != float("inf") else None,
        "tenure_months": round(tenure_months, 1),
        "utilization": round(utilization, 3),
        "borrow_frequency": round(borrow_freq, 2),
        "points_breakdown": breakdown,
    }


def score_all_customers(
    customers: pd.DataFrame,
    ledger: pd.DataFrame,
    repayments: pd.DataFrame,
    snapshot_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Score all active customers and return a scored DataFrame.
    """
    rows = []
    for _, cust in customers[customers["is_active"]].iterrows():
        result = score_customer(
            customer_id=cust["customer_id"],
            ledger=ledger,
            repayments=repayments,
            snapshot_date=snapshot_date,
            tenure_start=pd.Timestamp(cust["tenure_start"]),
        )
        rows.append(result)

    df = pd.DataFrame(rows)
    # flatten points_breakdown into columns
    breakdown_df = pd.json_normalize(df["points_breakdown"]).add_prefix("pts_")
    df = pd.concat([df.drop(columns=["points_breakdown"]), breakdown_df], axis=1)
    return df


def suggest_credit_limit(
    score_result: dict,
    ledger: pd.DataFrame,
    estimated_working_capital: float,
    active_customer_count: int,
) -> float:
    """
    Suggest a per-customer credit limit.

    The limit is the minimum of:
        1. Capacity from repayment history: the customer's average
           cleared debt amount, adjusted up for Hijau and down for Merah.
        2. Shop's budget share: the shop's total credit budget
           (CREDIT_BUDGET_FRACTION * working_capital) divided equally
           among active kasbon customers.

    This links the individual limit to the shop's cash position.
    """
    customer_id = score_result["customer_id"]
    band = score_result["band"]

    if band == "thin_file":
        # conservative limit for new customers: 25k IDR
        return 25000.0

    cust_cleared = ledger[(ledger["customer_id"] == customer_id) & (ledger["is_cleared"])]
    if cust_cleared.empty:
        capacity = 25000.0
    else:
        avg_cleared = cust_cleared["amount"].mean()
        band_multiplier = {"hijau": 1.5, "kuning": 1.0, "merah": 0.5}.get(band, 1.0)
        capacity = avg_cleared * band_multiplier

    # shop budget share
    total_budget = estimated_working_capital * CREDIT_BUDGET_FRACTION
    budget_share = total_budget / max(active_customer_count, 1)

    limit = min(capacity, budget_share)
    # round to nearest 5k
    return round(limit / 5000) * 5000


def band_from_score(score: float) -> str:
    """Map a numeric score to a credit band."""
    if score >= BAND_THRESHOLDS["hijau"]:
        return "hijau"
    if score >= BAND_THRESHOLDS["kuning"]:
        return "kuning"
    return "merah"
