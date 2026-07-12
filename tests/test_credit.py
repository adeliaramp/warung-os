"""
Tests for analytics/credit.py using synthetic data.
"""

import pandas as pd
import pytest

from analytics.credit import (
    band_from_score,
    score_all_customers,
    suggest_credit_limit,
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


# ---------------------------------------------------------------------------
# band_from_score
# ---------------------------------------------------------------------------


def test_band_hijau():
    assert band_from_score(75) == "hijau"


def test_band_kuning():
    assert band_from_score(60) == "kuning"


def test_band_merah():
    assert band_from_score(40) == "merah"


def test_band_boundary_hijau():
    assert band_from_score(70) == "hijau"


def test_band_boundary_kuning():
    assert band_from_score(50) == "kuning"


# ---------------------------------------------------------------------------
# score_all_customers
# ---------------------------------------------------------------------------


def test_score_returns_dataframe(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    assert isinstance(scores, pd.DataFrame)
    assert len(scores) == len(customers[customers["is_active"]])


def test_score_required_columns(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    for col in ["customer_id", "score", "band", "on_time_ratio", "tenure_months"]:
        assert col in scores.columns


def test_score_bands_are_valid(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    valid_bands = {"hijau", "kuning", "merah", "thin_file"}
    assert set(scores["band"].unique()).issubset(valid_bands)


def test_score_in_range(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    scored = scores[scores["score"].notna()]
    assert (scored["score"] >= 0).all()
    assert (scored["score"] <= 100).all()


def test_hijau_higher_than_merah_on_average(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    hijau_mean = scores[scores["band"] == "hijau"]["score"].mean()
    merah_mean = scores[scores["band"] == "merah"]["score"].mean()
    assert hijau_mean > merah_mean


# ---------------------------------------------------------------------------
# suggest_credit_limit
# ---------------------------------------------------------------------------


def test_suggest_limit_positive(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    for _, row in scores.iterrows():
        limit = suggest_credit_limit(row.to_dict(), ledger, 5_000_000.0, 40)
        assert limit >= 0


def test_thin_file_gets_conservative_limit(customers, ledger, repayments):
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    thin = scores[scores["band"] == "thin_file"]
    for _, row in thin.iterrows():
        limit = suggest_credit_limit(row.to_dict(), ledger, 5_000_000.0, 40)
        assert limit <= 50_000, "Thin-file limit should be conservative"
