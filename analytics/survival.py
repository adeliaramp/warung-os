"""
Repayment survival analysis using a Cox proportional hazards model.

The model predicts P(debt repaid within 30 days) for each open kasbon debt.
Falls back to Kaplan-Meier band averages when fewer than MIN_CLOSED_DEBTS
closed debts are available (cold start / early merchant use).

Covariates used:
    - log_amount      : log(debt amount in IDR) — larger debts take longer
    - tenure_months   : months customer has been with the shop
    - days_since_payday : distance to nearest 1st or 15th of the month
"""

from __future__ import annotations

import datetime
import math

import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter

# minimum closed debts required to fit the Cox model; fall back to KM below this
MIN_CLOSED_DEBTS = 20


def days_since_payday(borrow_date: datetime.date | pd.Timestamp) -> int:
    """
    Return the number of days since the nearest payday (1st or 15th of month).

    Indonesian warung customers typically receive wages on the 1st and 15th,
    so proximity to payday is a proxy for repayment capacity.
    """
    if isinstance(borrow_date, pd.Timestamp):
        borrow_date = borrow_date.date()

    day = borrow_date.day

    # distance to 1st of this month
    dist_first = day - 1

    # distance to 15th of this month (could be negative if day < 15)
    dist_fifteenth = abs(day - 15)

    return int(min(dist_first, dist_fifteenth))


def build_survival_dataset(
    ledger: pd.DataFrame,
    repayments: pd.DataFrame,
    customers: pd.DataFrame,
    snapshot: pd.Timestamp,
) -> pd.DataFrame:
    """
    Construct the survival dataset from the kasbon ledger.

    Each row is one debt. The survival outcome is:
        duration  = days from borrowed_at to either full repayment or snapshot
        event     = 1 if debt was fully repaid, 0 if still open (censored)

    Debts with missing covariates are dropped.

    Returns a DataFrame with columns:
        ledger_id, customer_id, duration, event,
        log_amount, tenure_months, days_since_payday, band (if available)
    """
    if ledger.empty:
        return pd.DataFrame()

    # ensure datetime types
    ledger = ledger.copy()
    ledger["borrowed_at"] = pd.to_datetime(ledger["borrowed_at"])

    rows = []

    for _, debt in ledger.iterrows():
        ledger_id = int(debt["ledger_id"])
        customer_id = int(debt["customer_id"])
        amount = float(debt["amount"])
        borrowed_at = debt["borrowed_at"]

        # total repaid for this debt
        debt_repayments = repayments[repayments["ledger_id"] == ledger_id]

        is_cleared = bool(debt["is_cleared"])

        if is_cleared and not debt_repayments.empty:
            # use the date of the final repayment as the event time
            last_repaid = pd.to_datetime(debt_repayments["repaid_at"]).max()
            duration = max(1, (last_repaid - borrowed_at).days)
            event = 1
        else:
            # censored: still open as of snapshot
            duration = max(1, (snapshot - borrowed_at).days)
            event = 0

        # log-transform amount (IDR amounts span several orders of magnitude)
        log_amount = math.log(max(amount, 1.0))

        # customer tenure
        cust_row = customers[customers["customer_id"] == customer_id]
        if cust_row.empty:
            continue
        tenure_start = pd.to_datetime(cust_row.iloc[0]["tenure_start"])
        tenure_months = max(0, (borrowed_at - tenure_start).days / 30.0)

        payday_dist = days_since_payday(borrowed_at)

        rows.append(
            {
                "ledger_id": ledger_id,
                "customer_id": customer_id,
                "duration": duration,
                "event": event,
                "log_amount": log_amount,
                "tenure_months": tenure_months,
                "days_since_payday": payday_dist,
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


COVARIATES = ["log_amount", "tenure_months", "days_since_payday"]


def fit_cox(survival_df: pd.DataFrame) -> CoxPHFitter | None:
    """
    Fit a Cox proportional hazards model on closed debts.

    Returns None if there are fewer than MIN_CLOSED_DEBTS closed debts
    (caller should fall back to KM estimator).
    """
    closed = survival_df[survival_df["event"] == 1]
    if len(closed) < MIN_CLOSED_DEBTS:
        return None

    # CoxPHFitter expects a DataFrame with duration, event, and covariate columns
    fit_df = survival_df[["duration", "event"] + COVARIATES].dropna().copy()
    if len(fit_df[fit_df["event"] == 1]) < MIN_CLOSED_DEBTS:
        return None

    cph = CoxPHFitter(penalizer=0.1)
    cph.fit(fit_df, duration_col="duration", event_col="event")
    return cph


def _km_p30_by_band(survival_df: pd.DataFrame, band_map: dict[int, str]) -> dict[str, float]:
    """
    Compute KM-estimated P(repaid within 30 days) per credit band.
    Used as fallback when Cox cannot be fit.
    """
    survival_df = survival_df.copy()
    survival_df["band"] = survival_df["customer_id"].map(band_map).fillna("unknown")

    results: dict[str, float] = {}
    for band, group in survival_df.groupby("band"):
        kmf = KaplanMeierFitter()
        kmf.fit(group["duration"], event_observed=group["event"])
        # S(30) = P(not yet repaid by day 30), so P(repaid by 30) = 1 - S(30)
        s30 = kmf.survival_function_at_times([30]).iloc[0]
        results[str(band)] = float(1.0 - s30)

    return results


def predict_p30(
    survival_df: pd.DataFrame,
    open_ledger: pd.DataFrame,
    cox_model: CoxPHFitter | None,
    band_map: dict[int, str],
) -> pd.DataFrame:
    """
    Predict P(repaid within 30 days) for each open debt.

    If cox_model is provided, uses Cox-predicted survival curves.
    Otherwise falls back to the KM band average.

    Parameters
    ----------
    survival_df   : full survival dataset (all debts, closed + open)
    open_ledger   : rows from kasbon_ledger where is_cleared = False
    cox_model     : fitted CoxPHFitter or None
    band_map      : dict mapping customer_id → credit band string

    Returns
    -------
    DataFrame with columns: ledger_id, p30, model_type
    """
    if open_ledger.empty:
        return pd.DataFrame(columns=["ledger_id", "p30", "model_type"])

    # rows in survival_df corresponding to open debts
    open_rows = survival_df[survival_df["ledger_id"].isin(open_ledger["ledger_id"])].copy()
    if open_rows.empty:
        return pd.DataFrame(columns=["ledger_id", "p30", "model_type"])

    results = []

    if cox_model is not None:
        # Cox path: use the model's predicted survival function per row
        covariate_df = open_rows[COVARIATES].fillna(0.0)

        # predict_survival_function returns a DataFrame: index = time points, cols = row indices
        sf = cox_model.predict_survival_function(covariate_df, times=[30])

        for idx, row in open_rows.iterrows():
            ledger_id = int(row["ledger_id"])
            # sf.loc[30, position] — position in covariate_df
            position = list(open_rows.index).index(idx)
            s30 = float(sf.iloc[0, position])
            p30 = round(1.0 - s30, 4)
            results.append({"ledger_id": ledger_id, "p30": p30, "model_type": "cox"})

    else:
        # KM fallback: assign band average to each open debt
        km_p30 = _km_p30_by_band(survival_df, band_map)
        fallback_default = 0.5  # neutral prior when no history exists

        for _, row in open_rows.iterrows():
            ledger_id = int(row["ledger_id"])
            cid = int(row["customer_id"])
            band = band_map.get(cid, "unknown")
            p30 = km_p30.get(band, fallback_default)
            results.append(
                {"ledger_id": ledger_id, "p30": round(p30, 4), "model_type": "km_fallback"}
            )

    return pd.DataFrame(results)
