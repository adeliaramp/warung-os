"""
Pre-render all portfolio figures to docs/assets/.

Run once after training the models on synthetic data:
    python scripts/generate_portfolio_assets.py

Outputs:
    docs/assets/demand_classification.png
    docs/assets/restock_policy.png
    docs/assets/survival_curves.png
    docs/assets/credit_scorecard.png
"""

from __future__ import annotations

import os
import sys

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = "data/synthetic/output/"
OUT_DIR = "docs/assets/"
SNAPSHOT = pd.Timestamp("2024-12-31")

os.makedirs(OUT_DIR, exist_ok=True)


def _save(fig: plt.Figure, name: str) -> None:
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {path}")


# ---------------------------------------------------------------------------
# Figure 1: Demand classification scatter (ADI vs CV²)
# ---------------------------------------------------------------------------


def fig_demand_classification() -> None:
    from analytics.classifier import classify_all_skus

    sales = pd.read_csv(DATA_DIR + "sales.csv", parse_dates=["sale_date"])
    skus = pd.read_csv(DATA_DIR + "skus.csv")

    classified = classify_all_skus(sales, skus)

    COLORS = {
        "smooth": "#2ecc71",
        "erratic": "#f39c12",
        "intermittent": "#3498db",
        "lumpy": "#e74c3c",
    }

    fig, ax = plt.subplots(figsize=(7, 5))

    for demand_class, group in classified.groupby("demand_class"):
        ax.scatter(
            group["adi"],
            group["cv2"],
            label=demand_class.capitalize(),
            color=COLORS.get(demand_class, "grey"),
            alpha=0.75,
            s=40,
        )

    # Syntetos-Boylan threshold lines
    ax.axvline(x=1.32, color="black", linewidth=0.8, linestyle="--")
    ax.axhline(y=0.49, color="black", linewidth=0.8, linestyle="--")

    ax.set_xlabel("ADI (Average Demand Interval)")
    ax.set_ylabel("CV² (Squared Coefficient of Variation)")
    ax.set_title(
        "Demand Classification (Syntetos-Boylan)\n"
        "Each point is one SKU; dashed lines are the ADI=1.32, CV²=0.49 thresholds"
    )
    ax.legend(title="Class")
    fig.tight_layout()
    _save(fig, "demand_classification.png")


# ---------------------------------------------------------------------------
# Figure 2: ROP policy: simulated stock path for one dry SKU
# ---------------------------------------------------------------------------


def fig_restock_policy() -> None:
    from analytics.restock import run_restock

    sales = pd.read_csv(DATA_DIR + "sales.csv", parse_dates=["sale_date"])
    skus = pd.read_csv(DATA_DIR + "skus.csv")

    recs = run_restock(sales, skus)

    # pick the dry SKU with the highest daily_rate for a clean illustration
    dry = recs[(~recs["is_perishable"]) & recs["rop"].notna()].copy()
    if dry.empty:
        print("  No dry SKU with ROP: skipping restock policy figure.")
        return

    target = dry.sort_values("daily_rate", ascending=False).iloc[0]
    sku_id = int(target["sku_id"])
    sku_row = skus[skus["sku_id"] == sku_id].iloc[0]
    sku_name = sku_row["name"]
    rop = float(target["rop"])
    order_qty = float(target["order_qty"])
    daily_rate = float(target["daily_rate"])

    # simulate a 60-day stock path starting at 2× order_qty
    import numpy as np

    rng = np.random.default_rng(42)
    days = 60
    stock = order_qty * 2.0
    history = [stock]

    for _ in range(days - 1):
        demand = rng.poisson(daily_rate)
        stock = max(0.0, stock - demand)
        if stock <= rop:
            stock += order_qty
        history.append(stock)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(range(days), history, color="#2980b9", linewidth=1.4)
    ax.axhline(rop, color="#e74c3c", linewidth=1.0, linestyle="--", label=f"ROP = {rop:.0f}")
    ax.set_xlabel("Day")
    ax.set_ylabel("Stock (units)")
    ax.set_title(
        f"Reorder Point Policy: {sku_name}\n"
        f"Order {order_qty:.0f} units when stock ≤ {rop:.0f} (simulated 60-day path)"
    )
    ax.legend()
    fig.tight_layout()
    _save(fig, "restock_policy.png")


# ---------------------------------------------------------------------------
# Figure 3: Kaplan-Meier survival curves by credit band
# ---------------------------------------------------------------------------


def fig_survival_curves() -> None:
    from lifelines import KaplanMeierFitter
    from analytics.survival import build_survival_dataset
    from analytics.credit import score_all_customers

    customers = pd.read_csv(DATA_DIR + "customers.csv", parse_dates=["tenure_start", "consent_at"])
    ledger = pd.read_csv(DATA_DIR + "kasbon_ledger.csv", parse_dates=["borrowed_at"])
    repayments = pd.read_csv(DATA_DIR + "kasbon_repayments.csv", parse_dates=["repaid_at"])

    survival_df = build_survival_dataset(ledger, repayments, customers, SNAPSHOT)
    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    band_map = dict(zip(scores["customer_id"].astype(int), scores["band"]))
    survival_df["band"] = survival_df["customer_id"].map(band_map).fillna("unknown")

    BAND_COLORS = {"hijau": "#27ae60", "kuning": "#f39c12", "merah": "#c0392b"}

    fig, ax = plt.subplots(figsize=(7, 5))

    for band in ["hijau", "kuning", "merah"]:
        group = survival_df[survival_df["band"] == band]
        if group.empty:
            continue
        kmf = KaplanMeierFitter()
        kmf.fit(group["duration"], event_observed=group["event"], label=band.capitalize())
        kmf.plot_survival_function(ax=ax, color=BAND_COLORS[band], ci_show=True)

    ax.axvline(x=30, color="black", linewidth=0.8, linestyle=":", label="30-day mark")
    ax.set_xlabel("Days since borrowing")
    ax.set_ylabel("P(not yet repaid)")
    ax.set_title(
        "Repayment Survival Curves by Credit Band\n"
        "Lower curve = faster repayment; shaded band = 95% CI"
    )
    ax.legend()
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    _save(fig, "survival_curves.png")


# ---------------------------------------------------------------------------
# Figure 4: Credit scorecard distribution
# ---------------------------------------------------------------------------


def fig_credit_scorecard() -> None:
    from analytics.credit import score_all_customers

    customers = pd.read_csv(DATA_DIR + "customers.csv", parse_dates=["tenure_start", "consent_at"])
    ledger = pd.read_csv(DATA_DIR + "kasbon_ledger.csv", parse_dates=["borrowed_at"])
    repayments = pd.read_csv(DATA_DIR + "kasbon_repayments.csv", parse_dates=["repaid_at"])

    scores = score_all_customers(customers, ledger, repayments, SNAPSHOT)
    scored = scores[scores["score"].notna()].copy()

    BAND_COLORS = {
        "hijau": "#27ae60",
        "kuning": "#f39c12",
        "merah": "#c0392b",
        "thin_file": "#95a5a6",
    }

    fig, ax = plt.subplots(figsize=(7, 4))

    for band, group in scored.groupby("band"):
        ax.hist(
            group["score"],
            bins=10,
            alpha=0.7,
            label=band.capitalize(),
            color=BAND_COLORS.get(band, "grey"),
        )

    ax.axvline(x=70, color="#27ae60", linewidth=1.0, linestyle="--")
    ax.axvline(x=50, color="#f39c12", linewidth=1.0, linestyle="--")
    ax.set_xlabel("Credit Score (0–100)")
    ax.set_ylabel("Number of customers")
    ax.set_title(
        "Credit Scorecard Distribution\n"
        "Hijau ≥70, Kuning 50–69, Merah <50 | dashed lines = band boundaries"
    )
    ax.legend(title="Band")
    fig.tight_layout()
    _save(fig, "credit_scorecard.png")


if __name__ == "__main__":
    print("Generating portfolio assets ...")
    fig_demand_classification()
    fig_restock_policy()
    fig_survival_curves()
    fig_credit_scorecard()
    print("Done. Files written to docs/assets/")
