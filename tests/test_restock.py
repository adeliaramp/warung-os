"""
Tests for analytics/restock.py.

All tests use the synthetic data CSVs so they run without a live database.
"""

import pandas as pd
import pytest

from analytics.restock import run_restock


DATA_DIR = "data/synthetic/output/"


@pytest.fixture(scope="module")
def sales():
    return pd.read_csv(DATA_DIR + "sales.csv", parse_dates=["sale_date"])


@pytest.fixture(scope="module")
def skus():
    return pd.read_csv(DATA_DIR + "skus.csv")


def test_run_restock_returns_dataframe(sales, skus):
    recs = run_restock(sales, skus)
    assert isinstance(recs, pd.DataFrame)
    assert len(recs) > 0


def test_required_columns(sales, skus):
    recs = run_restock(sales, skus)
    for col in ["sku_id", "demand_class", "daily_rate", "rop", "order_qty", "is_perishable"]:
        assert col in recs.columns, f"Missing column: {col}"


def test_perishables_have_null_rop(sales, skus):
    recs = run_restock(sales, skus)
    perishable_recs = recs[recs["is_perishable"]]
    assert perishable_recs["rop"].isna().all(), "Perishable SKUs should have null ROP"


def test_dry_goods_have_rop(sales, skus):
    recs = run_restock(sales, skus)
    dry_recs = recs[~recs["is_perishable"]]
    assert dry_recs["rop"].notna().all(), "Dry goods should have a computed ROP"


def test_demand_classes_are_valid(sales, skus):
    recs = run_restock(sales, skus)
    valid = {"smooth", "erratic", "intermittent", "lumpy"}
    assert set(recs["demand_class"].unique()).issubset(valid)


def test_order_qty_positive(sales, skus):
    recs = run_restock(sales, skus)
    assert (recs["order_qty"].dropna() > 0).all()


def test_daily_rate_nonnegative(sales, skus):
    recs = run_restock(sales, skus)
    assert (recs["daily_rate"] >= 0).all()


def test_rop_greater_than_zero_for_dry_goods(sales, skus):
    recs = run_restock(sales, skus)
    dry = recs[~recs["is_perishable"]]
    # ROP should be positive for items with real demand
    assert (dry["rop"] > 0).all()
