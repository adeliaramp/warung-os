"""
Tests for analytics/survival.py using synthetic data.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from analytics.survival import (
    build_survival_dataset,
    days_since_payday,
    fit_cox,
    predict_p30,
)

DATA_DIR = "data/synthetic/output/"

SNAPSHOT = pd.Timestamp("2024-12-31")


@pytest.fixture(scope="module")
def customers():
    return pd.read_csv(DATA_DIR + "customers.csv", parse_dates=["tenure_start", "consent_at"])


@pytest.fixture(scope="module")
def ledger():
    return pd.read_csv(DATA_DIR + "kasbon_ledger.csv", parse_dates=["borrowed_at"])


@pytest.fixture(scope="module")
def repayments():
    return pd.read_csv(DATA_DIR + "kasbon_repayments.csv", parse_dates=["repaid_at"])


@pytest.fixture(scope="module")
def survival_df(customers, ledger, repayments):
    return build_survival_dataset(ledger, repayments, customers, SNAPSHOT)


# ---------------------------------------------------------------------------
# days_since_payday
# ---------------------------------------------------------------------------


def test_payday_first_of_month():
    # 1st of month → 0 days since payday
    assert days_since_payday(datetime.date(2024, 6, 1)) == 0


def test_payday_fifteenth():
    # 15th of month → 0 days since payday
    assert days_since_payday(datetime.date(2024, 6, 15)) == 0


def test_payday_midpoint():
    # 8th is 7 days after 1st, 7 days before 15th → 7
    assert days_since_payday(datetime.date(2024, 6, 8)) == 7


def test_payday_non_negative():
    for day in range(1, 29):
        d = datetime.date(2024, 6, day)
        assert days_since_payday(d) >= 0


# ---------------------------------------------------------------------------
# build_survival_dataset
# ---------------------------------------------------------------------------


def test_survival_df_is_dataframe(survival_df):
    assert isinstance(survival_df, pd.DataFrame)


def test_survival_df_required_columns(survival_df):
    for col in [
        "ledger_id",
        "customer_id",
        "duration",
        "event",
        "log_amount",
        "tenure_months",
        "days_since_payday",
    ]:
        assert col in survival_df.columns


def test_duration_positive(survival_df):
    assert (survival_df["duration"] >= 1).all()


def test_event_binary(survival_df):
    assert set(survival_df["event"].unique()).issubset({0, 1})


def test_log_amount_positive(survival_df):
    assert (survival_df["log_amount"] > 0).all()


# ---------------------------------------------------------------------------
# fit_cox
# ---------------------------------------------------------------------------


def test_fit_cox_returns_model_with_enough_data(survival_df):
    # synthetic dataset should have >= 20 closed debts
    model = fit_cox(survival_df)
    assert model is not None


def test_fit_cox_returns_none_when_insufficient():
    # only 5 closed debts — should return None
    tiny = pd.DataFrame(
        {
            "duration": [5, 10, 20, 30, 45] + [60] * 15,
            "event": [1, 1, 1, 1, 1] + [0] * 15,
            "log_amount": [10.0] * 20,
            "tenure_months": [6.0] * 20,
            "days_since_payday": [3] * 20,
        }
    )
    assert fit_cox(tiny) is None


# ---------------------------------------------------------------------------
# predict_p30
# ---------------------------------------------------------------------------


def test_predict_p30_shape(customers, ledger, repayments, survival_df):
    open_ledger = ledger[~ledger["is_cleared"]]
    model = fit_cox(survival_df)
    band_map: dict[int, str] = {
        int(r["customer_id"]): "hijau" for r in customers.to_dict("records")
    }
    preds = predict_p30(survival_df, open_ledger, model, band_map)
    assert isinstance(preds, pd.DataFrame)
    assert len(preds) == len(open_ledger[open_ledger["ledger_id"].isin(survival_df["ledger_id"])])


def test_predict_p30_in_range(customers, ledger, repayments, survival_df):
    open_ledger = ledger[~ledger["is_cleared"]]
    model = fit_cox(survival_df)
    band_map: dict[int, str] = {
        int(r["customer_id"]): "hijau" for r in customers.to_dict("records")
    }
    preds = predict_p30(survival_df, open_ledger, model, band_map)
    assert (preds["p30"] >= 0.0).all()
    assert (preds["p30"] <= 1.0).all()


def test_predict_p30_km_fallback(customers, ledger, repayments, survival_df):
    open_ledger = ledger[~ledger["is_cleared"]]
    band_map: dict[int, str] = {
        int(r["customer_id"]): "hijau" for r in customers.to_dict("records")
    }
    # pass None for model to force KM fallback
    preds = predict_p30(survival_df, open_ledger, None, band_map)
    assert (preds["model_type"] == "km_fallback").all()
    assert (preds["p30"] >= 0.0).all()
    assert (preds["p30"] <= 1.0).all()
