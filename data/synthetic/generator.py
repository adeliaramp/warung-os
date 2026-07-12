"""
Synthetic warung data generator.

Produces 12 months of realistic sales, stock, and kasbon history
for ~120 SKUs and ~40 repeat customers. All randomness is seeded
so output is fully reproducible.

Usage:
    python -m data.synthetic.generator --seed 42 --output data/synthetic/output/

Output files (CSV):
    skus.csv
    sales.csv
    stock_log.csv
    customers.csv
    kasbon_ledger.csv
    kasbon_repayments.csv
"""

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# SKU catalog definition
# Each entry: (name, unit, category, is_perishable, cost_price, sell_price,
#              target_demand_class)
# target_demand_class controls which statistical parameters are used when
# generating daily sales. The generator will produce data whose ADI and CV²
# land in the correct Syntetos-Boylan quadrant for each SKU.
# ---------------------------------------------------------------------------

SKU_TEMPLATES = [
    # --- dry / packaged ---
    ("Indomie Goreng", "bungkus", "dry", False, 2500, 3000, "smooth"),
    ("Indomie Kuah", "bungkus", "dry", False, 2500, 3000, "smooth"),
    ("Indomie Soto", "bungkus", "dry", False, 2500, 3000, "smooth"),
    ("Mie Sedaap Goreng", "bungkus", "dry", False, 2500, 3000, "smooth"),
    ("Mie Sedaap Kuah", "bungkus", "dry", False, 2500, 3000, "smooth"),
    ("Beras 5kg", "karung", "dry", False, 62000, 70000, "smooth"),
    ("Beras 1kg", "kg", "dry", False, 12500, 14000, "erratic"),
    ("Gula Pasir 1kg", "kg", "dry", False, 14000, 16000, "smooth"),
    ("Gula Pasir 250g", "bungkus", "dry", False, 3500, 4000, "erratic"),
    ("Minyak Goreng 1L", "liter", "dry", False, 18000, 21000, "smooth"),
    ("Minyak Goreng 500ml", "botol", "dry", False, 10000, 12000, "erratic"),
    ("Kecap Manis ABC 135ml", "botol", "dry", False, 5000, 6000, "intermittent"),
    ("Kecap Manis ABC 275ml", "botol", "dry", False, 9000, 11000, "intermittent"),
    ("Saos Sambal ABC", "botol", "dry", False, 7000, 8500, "intermittent"),
    ("Garam 250g", "bungkus", "dry", False, 2000, 2500, "intermittent"),
    ("Tepung Terigu 1kg", "kg", "dry", False, 10000, 12000, "intermittent"),
    ("Tepung Beras 500g", "bungkus", "dry", False, 6000, 7500, "lumpy"),
    ("Kopi Kapal Api Sachet", "sachet", "dry", False, 1500, 2000, "smooth"),
    ("Kopi Nescafe Sachet", "sachet", "dry", False, 2000, 2500, "smooth"),
    ("Teh Celup Sariwangi", "kotak", "dry", False, 7000, 8500, "smooth"),
    ("Susu Kental Manis Frisian Flag", "kaleng", "dry", False, 12000, 14000, "erratic"),
    ("Susu Kental Manis Indomilk", "kaleng", "dry", False, 11000, 13000, "erratic"),
    ("Energen Cokelat", "sachet", "dry", False, 4000, 5000, "intermittent"),
    ("Milo Sachet", "sachet", "dry", False, 3500, 4500, "intermittent"),
    ("Ovomaltine Sachet", "sachet", "dry", False, 4500, 5500, "lumpy"),
    ("Rokok Gudang Garam 12", "bungkus", "dry", False, 23000, 25000, "smooth"),
    ("Rokok Surya 12", "bungkus", "dry", False, 21000, 23000, "smooth"),
    ("Rokok Marlboro 20", "bungkus", "dry", False, 38000, 42000, "erratic"),
    ("Rokok Dji Sam Soe 12", "bungkus", "dry", False, 24000, 27000, "erratic"),
    ("Rokok Ecer", "batang", "dry", False, 1700, 2000, "smooth"),
    # snacks
    ("Chitato Sapi Panggang", "bungkus", "snack", False, 7000, 8500, "smooth"),
    ("Chitato Original", "bungkus", "snack", False, 7000, 8500, "smooth"),
    ("Piattos Keju", "bungkus", "snack", False, 7000, 8500, "erratic"),
    ("Oreo Original", "bungkus", "snack", False, 5000, 6000, "smooth"),
    ("Roma Kelapa", "bungkus", "snack", False, 5000, 6000, "smooth"),
    ("Beng-Beng", "pcs", "snack", False, 3000, 3500, "smooth"),
    ("Silver Queen Chunky Bar", "pcs", "snack", False, 11000, 13000, "intermittent"),
    ("Kopiko Candy", "bungkus", "snack", False, 2000, 2500, "intermittent"),
    ("Wafer Tango", "bungkus", "snack", False, 3500, 4500, "erratic"),
    ("Nabati Keju", "bungkus", "snack", False, 2500, 3000, "smooth"),
    # --- beverages ---
    ("Aqua 600ml", "botol", "beverage", False, 3000, 4000, "smooth"),
    ("Aqua 1500ml", "botol", "beverage", False, 5500, 7000, "erratic"),
    ("Le Minerale 600ml", "botol", "beverage", False, 2800, 3500, "smooth"),
    ("Teh Botol Sosro 450ml", "botol", "beverage", False, 4500, 5500, "smooth"),
    ("Teh Pucuk Harum 350ml", "botol", "beverage", False, 3500, 4500, "smooth"),
    ("Pocari Sweat 330ml", "botol", "beverage", False, 5000, 6500, "erratic"),
    ("Extra Joss Sachet", "sachet", "beverage", False, 2500, 3000, "intermittent"),
    ("Sprite 390ml", "botol", "beverage", False, 4500, 5500, "erratic"),
    ("Coca-Cola 390ml", "botol", "beverage", False, 4500, 5500, "erratic"),
    ("Good Day Cappuccino", "botol", "beverage", False, 4000, 5000, "intermittent"),
    ("Susu Ultra Mimi 125ml", "kotak", "beverage", False, 3000, 3800, "smooth"),
    ("Milo UHT 200ml", "kotak", "beverage", False, 5000, 6000, "intermittent"),
    ("Yakult", "botol", "beverage", False, 4500, 5500, "smooth"),
    # --- household / personal care ---
    ("Sabun Lifebuoy Batang", "pcs", "household", False, 3500, 4500, "smooth"),
    ("Sabun Dettol Cair 250ml", "botol", "household", False, 22000, 26000, "lumpy"),
    ("Sunlight Cuci Piring 200ml", "botol", "household", False, 8000, 10000, "erratic"),
    ("Rinso Sachet 75g", "sachet", "household", False, 4000, 5000, "intermittent"),
    ("Attack Sachet 75g", "sachet", "household", False, 3500, 4500, "intermittent"),
    ("Shampoo Sunsilk Sachet", "sachet", "household", False, 1000, 1500, "smooth"),
    ("Shampoo Clear Sachet", "sachet", "household", False, 1000, 1500, "smooth"),
    ("Kondisioner Rejoice Sachet", "sachet", "household", False, 1000, 1500, "intermittent"),
    ("Pasta Gigi Pepsodent 75g", "tube", "household", False, 12000, 14500, "intermittent"),
    ("Sikat Gigi Formula", "pcs", "household", False, 8000, 10000, "lumpy"),
    ("Pembalut Charm Regular", "bungkus", "household", False, 15000, 18000, "lumpy"),
    ("Pampers S 4pcs", "bungkus", "household", False, 14000, 17000, "lumpy"),
    # --- fresh ---
    ("Tahu Putih", "pcs", "fresh", True, 500, 700, "smooth"),
    ("Tempe 1 papan", "papan", "fresh", True, 7000, 9000, "smooth"),
    ("Telur Ayam", "butir", "fresh", True, 2500, 3000, "smooth"),
    ("Telur Puyuh (10 butir)", "pack", "fresh", True, 7000, 9000, "intermittent"),
    ("Kangkung 1 ikat", "ikat", "fresh", True, 3000, 4000, "erratic"),
    ("Bayam 1 ikat", "ikat", "fresh", True, 3000, 4000, "erratic"),
    ("Wortel 250g", "bungkus", "fresh", True, 4000, 5500, "intermittent"),
    ("Buncis 250g", "bungkus", "fresh", True, 4500, 6000, "intermittent"),
    ("Tomat 250g", "bungkus", "fresh", True, 4000, 5500, "erratic"),
    ("Cabai Rawit 100g", "bungkus", "fresh", True, 5000, 7000, "erratic"),
    ("Bawang Merah 100g", "bungkus", "fresh", True, 4000, 5500, "intermittent"),
    ("Bawang Putih 100g", "bungkus", "fresh", True, 4500, 6000, "intermittent"),
    ("Pisang Kepok (sisir)", "sisir", "fresh", True, 10000, 13000, "intermittent"),
    ("Roti Tawar Sari Roti", "bungkus", "fresh", True, 16000, 19000, "smooth"),
    ("Roti Gandum Sari Roti", "bungkus", "fresh", True, 18000, 22000, "erratic"),
    ("Kerupuk Mentah 250g", "bungkus", "fresh", True, 5000, 7000, "lumpy"),
    # --- frozen ---
    ("Bakso Sapi Frozen 500g", "bungkus", "frozen", True, 28000, 35000, "lumpy"),
    ("Nugget So Good 500g", "bungkus", "frozen", True, 35000, 42000, "lumpy"),
    ("Sosis Vida 375g", "bungkus", "frozen", True, 28000, 35000, "lumpy"),
    ("Es Krim Walls Paddle Pop", "pcs", "frozen", True, 5000, 7000, "intermittent"),
    ("Es Krim Campina", "pcs", "frozen", True, 6000, 8000, "intermittent"),
]


# ---------------------------------------------------------------------------
# Demand parameters per class
# These produce ADI / CV² values that land in the correct Syntetos-Boylan
# quadrant for 95%+ of generated SKUs at the end of 12 months.
# ---------------------------------------------------------------------------

DEMAND_PARAMS = {
    # (zero_prob, mean_nonzero, cv_nonzero)
    # zero_prob:    probability of zero demand on any given day
    # mean_nonzero: mean units sold on nonzero days
    # cv_nonzero:   CV of nonzero demand quantity (not CV²)
    "smooth": (0.10, 5.0, 0.50),  # ADI ~1.11, CV² ~0.25
    "erratic": (0.10, 5.0, 1.10),  # ADI ~1.11, CV² ~1.21
    "intermittent": (0.55, 4.0, 0.50),  # ADI ~2.22, CV² ~0.25
    "lumpy": (0.55, 4.0, 1.10),  # ADI ~2.22, CV² ~1.21
}


# ---------------------------------------------------------------------------
# Customer profiles for kasbon
# (credit_band, borrow_freq_per_month, typical_amount_range, repay_days_mean,
#  repay_days_std, miss_prob)
# ---------------------------------------------------------------------------

CUSTOMER_PROFILES = {
    "hijau": {
        "borrow_freq": (1.5, 3.0),  # borrows per month
        "amount": (20000, 80000),  # IDR per event
        "repay_days": (7, 3),  # mean, std days to repay
        "miss_prob": 0.02,  # prob of never repaying a debt
    },
    "kuning": {
        "borrow_freq": (2.0, 4.0),
        "amount": (30000, 100000),
        "repay_days": (18, 7),
        "miss_prob": 0.08,
    },
    "merah": {
        "borrow_freq": (3.0, 6.0),
        "amount": (40000, 120000),
        "repay_days": (35, 15),
        "miss_prob": 0.25,
    },
}

# 40 customers: 50% Hijau, 30% Kuning, 20% Merah
CUSTOMER_BAND_MIX = ["hijau"] * 20 + ["kuning"] * 12 + ["merah"] * 8


# ---------------------------------------------------------------------------
# Core generation functions
# ---------------------------------------------------------------------------


def make_skus(rng: np.random.Generator) -> pd.DataFrame:
    """Build the SKU catalog from templates, adding small price jitter."""
    rows = []
    for i, (name, unit, category, is_perishable, cost, sell, _) in enumerate(
        SKU_TEMPLATES, start=1
    ):
        # small random price variation so prices are not perfectly uniform
        jitter = rng.uniform(0.95, 1.05)
        rows.append(
            {
                "sku_id": i,
                "name": name,
                "unit": unit,
                "category": category,
                "is_perishable": is_perishable,
                "cost_price": round(cost * jitter / 100) * 100,
                "sell_price": round(sell * jitter / 100) * 100,
                "is_active": True,
            }
        )
    return pd.DataFrame(rows)


def make_daily_sales(
    skus: pd.DataFrame,
    start_date: date,
    end_date: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Generate daily sales for every SKU across the simulation period.

    Uses a negative binomial for nonzero demand sizes, which naturally
    produces the right CV² range without manual tuning. Zero-demand days
    are controlled by zero_prob for each demand class.
    """
    all_dates = pd.date_range(start_date, end_date, freq="D")
    n_days = len(all_dates)

    records = []

    for _, sku in skus.iterrows():
        sku_id = sku["sku_id"]
        demand_class = SKU_TEMPLATES[sku_id - 1][6]
        zero_prob, mean_nz, cv_nz = DEMAND_PARAMS[demand_class]

        # weekday multiplier: warung sells more Mon-Sat, less Sun
        weekday_mult = np.array([1.1, 1.1, 1.0, 1.0, 1.1, 1.2, 0.7] * (n_days // 7 + 1))[:n_days]

        # draw zero/nonzero indicator for each day
        is_nonzero = rng.random(n_days) > (zero_prob * weekday_mult)

        # negative binomial parameters from mean and CV
        # NB(r, p): mean = r*(1-p)/p, var = r*(1-p)/p²
        # -> r = mean / (cv² * mean - 1 + 1/mean)  ... simplified:
        # we use gamma-Poisson mixture to get NB with desired mean and var
        var_nz = (cv_nz * mean_nz) ** 2
        # clamp to avoid degenerate params
        var_nz = max(var_nz, mean_nz + 0.1)
        p_nb = mean_nz / var_nz  # p in (0,1)
        r_nb = mean_nz * p_nb / (1 - p_nb)  # r > 0

        qty_raw = rng.negative_binomial(max(r_nb, 0.5), min(p_nb, 0.99), n_days)
        qty_raw = np.where(qty_raw == 0, 1, qty_raw)  # nonzero days get at least 1 unit

        # apply zero mask and weekday scaling
        qty = np.where(is_nonzero, qty_raw, 0).astype(float)

        # add a small number of nulls (data entry gaps, ~1%)
        null_mask = rng.random(n_days) < 0.01
        qty = np.where(null_mask, np.nan, qty)

        for i, d in enumerate(all_dates):
            if not np.isnan(qty[i]) and qty[i] > 0:
                records.append(
                    {
                        "sale_id": None,  # assigned after concatenation
                        "sku_id": sku_id,
                        "quantity": float(qty[i]),
                        "sale_date": d.date(),
                        "source": "telegram",
                    }
                )

    df = pd.DataFrame(records)
    df = df.sort_values(["sale_date", "sku_id"]).reset_index(drop=True)
    df["sale_id"] = df.index + 1
    df = df[["sale_id", "sku_id", "quantity", "sale_date", "source"]]
    return df


def make_stock_log(
    skus: pd.DataFrame,
    sales: pd.DataFrame,
    start_date: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Generate stock snapshots.

    The merchant logs stock roughly once a week for each SKU,
    with some variation. Stock level = assumed starting stock
    minus cumulative sales since last restock, with random restocks.
    """
    records = []
    log_id = 1

    for _, sku in skus.iterrows():
        sku_id = sku["sku_id"]
        sku_sales = sales[sales["sku_id"] == sku_id].set_index("sale_date")["quantity"]

        # starting stock: roughly 14 days of average demand
        avg_daily = sku_sales.mean() if len(sku_sales) > 0 else 5.0
        stock = round(avg_daily * 14)

        current = start_date
        end = date(2024, 12, 31)

        while current <= end:
            # log stock every 5-10 days with some gaps
            days_to_next = rng.integers(5, 11)

            # consume sales in this window
            for d_offset in range(days_to_next):
                d = current + timedelta(days=d_offset)
                if d > end:
                    break
                sold = sku_sales.get(d, 0)
                if not np.isnan(sold):
                    stock = max(stock - sold, 0)

            # restock if running low (below 5 days of demand)
            reorder_threshold = round(avg_daily * 5)
            if stock < reorder_threshold:
                restock_qty = round(avg_daily * rng.uniform(10, 20))
                stock += restock_qty

            # log with small measurement noise
            logged_qty = max(0, stock + rng.integers(-2, 3))

            records.append(
                {
                    "log_id": log_id,
                    "sku_id": sku_id,
                    "quantity": float(logged_qty),
                    "logged_at": pd.Timestamp(current),
                    "source": "telegram",
                }
            )
            log_id += 1
            current += timedelta(days=int(days_to_next))

    df = pd.DataFrame(records)
    df = df.sort_values(["logged_at", "sku_id"]).reset_index(drop=True)
    return df


def make_customers(rng: np.random.Generator, start_date: date) -> pd.DataFrame:
    """Build a customer roster with randomized tenure start dates."""
    INITIALS_POOL = [
        "SR",
        "BU",
        "PA",
        "WA",
        "HE",
        "SU",
        "DE",
        "NU",
        "AN",
        "YU",
        "MA",
        "RA",
        "SI",
        "EM",
        "RO",
        "FI",
        "LA",
        "KA",
        "DA",
        "TU",
        "ZU",
        "IN",
        "HA",
        "BA",
        "MU",
        "SA",
        "NA",
        "WI",
        "AG",
        "JU",
        "TO",
        "AM",
        "PU",
        "DI",
        "EK",
        "RU",
        "TA",
        "BI",
        "CO",
        "LI",
    ]

    rows = []
    for i, (initials, band) in enumerate(zip(INITIALS_POOL, CUSTOMER_BAND_MIX), start=1):
        # tenure start: between 6 months before sim start and 2 months after
        offset_days = rng.integers(-180, 60)
        tenure_start = start_date + timedelta(days=int(offset_days))

        rows.append(
            {
                "customer_id": i,
                "local_code": f"CS-{i:03d}",
                "initials": initials,
                "credit_band": band,  # stored here for generation logic; not in prod schema
                "tenure_start": tenure_start,
                "consent_at": pd.Timestamp(tenure_start),
                "is_active": True,
            }
        )
    return pd.DataFrame(rows)


def make_kasbon(
    customers: pd.DataFrame,
    start_date: date,
    end_date: date,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate kasbon borrowing and repayment events.

    Repayment timing is driven by:
        - Customer's credit band (Hijau pays faster than Merah)
        - Payday cycle: 1st and 15th of each month; customers tend to
          repay more in the week after a payday
        - A miss_prob chance of the debt never being repaid
    """
    ledger_records = []
    repayment_records = []
    ledger_id = 1
    repayment_id = 1

    sim_days = (end_date - start_date).days

    for _, cust in customers.iterrows():
        cust_id = cust["customer_id"]
        band = cust["credit_band"]
        profile = CUSTOMER_PROFILES[band]

        # how many borrowing events across the simulation?
        freq_lo, freq_hi = profile["borrow_freq"]
        total_borrows = int(rng.uniform(freq_lo, freq_hi) * 12)

        # pick random borrow dates within the simulation period
        borrow_offsets = sorted(rng.integers(0, sim_days, size=total_borrows).tolist())

        for offset in borrow_offsets:
            borrow_date = start_date + timedelta(days=int(offset))

            # amount
            amt_lo, amt_hi = profile["amount"]
            amount = round(rng.uniform(amt_lo, amt_hi) / 1000) * 1000  # round to nearest 1k

            # will this debt ever be repaid?
            will_miss = rng.random() < profile["miss_prob"]

            # repayment timing
            repay_mean, repay_std = profile["repay_days"]

            # payday alignment: if borrow date is within 5 days before a payday,
            # slightly shorten expected repayment time
            day_of_month = borrow_date.day
            days_to_payday = min(
                (1 - day_of_month) % 15,
                (15 - day_of_month) % 15,
            )
            payday_boost = max(0, 5 - days_to_payday)  # up to 5 days earlier

            raw_repay_days = int(max(1, rng.normal(repay_mean - payday_boost, repay_std)))

            repay_date = borrow_date + timedelta(days=raw_repay_days)

            ledger_records.append(
                {
                    "ledger_id": ledger_id,
                    "customer_id": cust_id,
                    "amount": float(amount),
                    "note": None,
                    "borrowed_at": pd.Timestamp(borrow_date),
                    "is_cleared": not will_miss and repay_date <= end_date,
                }
            )

            if not will_miss and repay_date <= end_date:
                # ~30% chance of multiple partial repayments
                if rng.random() < 0.3:
                    partial_frac = rng.uniform(0.3, 0.7)
                    first_payment = round(amount * partial_frac / 1000) * 1000
                    second_payment = amount - first_payment

                    repayment_records.append(
                        {
                            "repayment_id": repayment_id,
                            "ledger_id": ledger_id,
                            "amount": float(first_payment),
                            "repaid_at": pd.Timestamp(
                                borrow_date + timedelta(days=raw_repay_days // 2)
                            ),
                        }
                    )
                    repayment_id += 1

                    repayment_records.append(
                        {
                            "repayment_id": repayment_id,
                            "ledger_id": ledger_id,
                            "amount": float(second_payment),
                            "repaid_at": pd.Timestamp(repay_date),
                        }
                    )
                    repayment_id += 1
                else:
                    repayment_records.append(
                        {
                            "repayment_id": repayment_id,
                            "ledger_id": ledger_id,
                            "amount": float(amount),
                            "repaid_at": pd.Timestamp(repay_date),
                        }
                    )
                    repayment_id += 1

            ledger_id += 1

    ledger_df = pd.DataFrame(ledger_records).sort_values("borrowed_at").reset_index(drop=True)
    repayment_df = (
        pd.DataFrame(repayment_records).sort_values("repaid_at").reset_index(drop=True)
        if repayment_records
        else pd.DataFrame(columns=["repayment_id", "ledger_id", "amount", "repaid_at"])
    )

    return ledger_df, repayment_df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate(seed: int = 42, output_dir: str = "data/synthetic/output") -> dict[str, pd.DataFrame]:
    """
    Run the full synthetic generation and return a dict of DataFrames.
    Also writes CSV files to output_dir.
    """
    rng = np.random.default_rng(seed)

    start_date = date(2024, 1, 1)
    end_date = date(2024, 12, 31)

    print(f"Generating synthetic warung data (seed={seed}) ...")

    skus = make_skus(rng)
    print(f"  SKUs: {len(skus)}")

    sales = make_daily_sales(skus, start_date, end_date, rng)
    print(f"  Sales records: {len(sales)}")

    stock_log = make_stock_log(skus, sales, start_date, rng)
    print(f"  Stock log records: {len(stock_log)}")

    customers = make_customers(rng, start_date)
    print(f"  Customers: {len(customers)}")

    kasbon_ledger, kasbon_repayments = make_kasbon(customers, start_date, end_date, rng)
    print(f"  Kasbon ledger entries: {len(kasbon_ledger)}")
    print(f"  Kasbon repayments: {len(kasbon_repayments)}")

    # drop the internal credit_band column before saving (not in prod schema)
    customers_export = customers.drop(columns=["credit_band"])

    datasets = {
        "skus": skus,
        "sales": sales,
        "stock_log": stock_log,
        "customers": customers_export,
        "kasbon_ledger": kasbon_ledger,
        "kasbon_repayments": kasbon_repayments,
    }

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for name, df in datasets.items():
        path = os.path.join(output_dir, f"{name}.csv")
        df.to_csv(path, index=False)
        print(f"  Wrote {path}")

    print("Done.")
    return datasets


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WarungOS synthetic data generator")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--output",
        default="data/synthetic/output",
        help="Output directory for CSV files",
    )
    args = parser.parse_args()
    generate(seed=args.seed, output_dir=args.output)
