"""
Demand classifier using Syntetos-Boylan thresholds.

Each SKU's sales history is reduced to two statistics:
    ADI  — average inter-demand interval (days between nonzero sales)
    CV2  — squared coefficient of variation of nonzero demand sizes

Thresholds (Syntetos & Boylan 2005):
    ADI threshold: 1.32
    CV2 threshold: 0.49

Quadrants:
    ADI < 1.32 and CV2 < 0.49  -> "smooth"       (Laris stabil)
    ADI < 1.32 and CV2 >= 0.49 -> "erratic"      (Laris naik turun)
    ADI >= 1.32 and CV2 < 0.49 -> "intermittent" (Sesekali laku)
    ADI >= 1.32 and CV2 >= 0.49-> "lumpy"        (Susah ditebak)
"""

import pandas as pd

ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49

DEMAND_CLASSES = {
    (False, False): "smooth",
    (False, True): "erratic",
    (True, False): "intermittent",
    (True, True): "lumpy",
}

BAHASA_LABELS = {
    "smooth": "Laris stabil",
    "erratic": "Laris naik turun",
    "intermittent": "Sesekali laku",
    "lumpy": "Susah ditebak",
}


def classify(adi: float, cv2: float) -> str:
    """Return the demand class label for a given ADI and CV2 pair."""
    return DEMAND_CLASSES[(adi >= ADI_THRESHOLD, cv2 >= CV2_THRESHOLD)]


def compute_adi(series: pd.Series) -> float:
    """
    Compute ADI from a daily demand series (may contain zeros and NaNs).

    ADI = total days in the series / number of days with nonzero demand.
    A value of 1.0 means demand occurred every single day.
    """
    series = series.dropna()
    nonzero_days = (series > 0).sum()
    if nonzero_days == 0:
        return float("inf")
    return len(series) / nonzero_days


def compute_cv2(series: pd.Series) -> float:
    """
    Compute CV² from the nonzero demand values in a daily demand series.

    CV² = (std of nonzero demand / mean of nonzero demand)²
    """
    nonzero = series.dropna()
    nonzero = nonzero[nonzero > 0]
    if len(nonzero) < 2:
        return 0.0
    mean = nonzero.mean()
    if mean == 0:
        return 0.0
    cv = nonzero.std() / mean
    return cv**2


def classify_all_skus(sales: pd.DataFrame, skus: pd.DataFrame) -> pd.DataFrame:
    """
    Classify every SKU in the catalog from a sales DataFrame.

    Parameters
    ----------
    sales : DataFrame with columns [sku_id, sale_date, quantity]
    skus  : DataFrame with columns [sku_id, name, ...]

    Returns
    -------
    DataFrame with columns [sku_id, name, adi, cv2, demand_class, bahasa_label]
    """
    # pivot to wide format: rows = date, columns = sku_id
    pivot = (
        sales.pivot_table(
            index="sale_date",
            columns="sku_id",
            values="quantity",
            aggfunc="sum",
        )
        .reindex(pd.date_range(sales["sale_date"].min(), sales["sale_date"].max(), freq="D"))
        .fillna(0)
    )

    rows = []
    for sku_id in skus["sku_id"]:
        if sku_id not in pivot.columns:
            continue
        col = pivot[sku_id]
        adi = compute_adi(col)
        cv2 = compute_cv2(col)
        demand_class = classify(adi, cv2)
        rows.append(
            {
                "sku_id": sku_id,
                "name": skus.loc[skus["sku_id"] == sku_id, "name"].values[0],
                "adi": round(adi, 3),
                "cv2": round(cv2, 3),
                "demand_class": demand_class,
                "bahasa_label": BAHASA_LABELS[demand_class],
            }
        )

    return pd.DataFrame(rows)
