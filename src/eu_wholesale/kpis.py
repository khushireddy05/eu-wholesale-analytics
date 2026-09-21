"""Business KPI calculations.

Deterministic, auditable metric logic shared by the Excel workbook, the Power
BI export and the AI narrative layer. Nothing here is estimated - these are
the arithmetic facts the rest of the project reasons about.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

VALUE_COLS = ("revenue_eur", "cost_eur", "margin_eur", "volume_units")


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------
def aggregate(df: pd.DataFrame, by: list[str],
              values: tuple[str, ...] = VALUE_COLS) -> pd.DataFrame:
    """Sum measures by the requested grain and re-derive ratio metrics.

    Ratios are always recomputed from the summed numerator and denominator -
    averaging a ratio across rows would silently weight every row equally.
    """
    cols = [c for c in values if c in df.columns]
    out = df.groupby(by, as_index=False)[cols].sum()
    if {"margin_eur", "revenue_eur"} <= set(out.columns):
        out["margin_pct"] = out["margin_eur"] / out["revenue_eur"].replace(0, np.nan)
    if {"revenue_eur", "volume_units"} <= set(out.columns):
        out["unit_price_eur"] = out["revenue_eur"] / out["volume_units"].replace(0, np.nan)
    return out


def add_period_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Derive year / quarter / month columns from ``year_month``."""
    out = df.copy()
    period = pd.PeriodIndex(out["year_month"], freq="M")
    out["year"] = period.year
    out["month_no"] = period.month
    out["quarter"] = [f"{p.year}-Q{p.quarter}" for p in period]
    return out


def monthly_series(df: pd.DataFrame, value: str = "revenue_eur",
                   by: list[str] | None = None) -> pd.DataFrame:
    """Monthly time series at the requested grain, gaps filled with zero."""
    by = by or []
    grouped = df.groupby(by + ["year_month"], as_index=False)[value].sum()
    if not by:
        return grouped.sort_values("year_month").reset_index(drop=True)
    months = sorted(df["year_month"].unique())
    keys = grouped[by].drop_duplicates()
    grid = keys.merge(pd.DataFrame({"year_month": months}), how="cross")
    return (grid.merge(grouped, on=by + ["year_month"], how="left")
                .fillna({value: 0.0})
                .sort_values(by + ["year_month"])
                .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Growth metrics
# ---------------------------------------------------------------------------
def add_growth(df: pd.DataFrame, value: str = "revenue_eur",
               by: list[str] | None = None, periods_per_year: int = 12) -> pd.DataFrame:
    """Add month-on-month, year-on-year and rolling-12-month metrics."""
    by = by or []
    out = df.sort_values(by + ["year_month"]).copy()
    grp = out.groupby(by, sort=False)[value] if by else out[value]

    if by:
        out["mom_pct"] = grp.pct_change(1)
        out["yoy_pct"] = grp.pct_change(periods_per_year)
        out["yoy_abs"] = grp.diff(periods_per_year)
        out["r12m"] = grp.transform(lambda s: s.rolling(periods_per_year, min_periods=1).sum())
    else:
        out["mom_pct"] = out[value].pct_change(1)
        out["yoy_pct"] = out[value].pct_change(periods_per_year)
        out["yoy_abs"] = out[value].diff(periods_per_year)
        out["r12m"] = out[value].rolling(periods_per_year, min_periods=1).sum()
    return out


def cagr(first_value: float, last_value: float, years: float) -> float:
    """Compound annual growth rate; NaN where undefined."""
    if years <= 0 or first_value <= 0 or last_value <= 0:
        return float("nan")
    return (last_value / first_value) ** (1.0 / years) - 1.0


def yoy_table(df: pd.DataFrame, by: str, value: str = "revenue_eur",
              months: int = 12) -> pd.DataFrame:
    """Rolling-12-month value by dimension, versus the prior 12 months."""
    all_months = sorted(df["year_month"].unique())
    current = all_months[-months:]
    prior = all_months[-2 * months:-months]

    cur = (df[df["year_month"].isin(current)].groupby(by, as_index=False)[value]
           .sum().rename(columns={value: "current_12m"}))
    pri = (df[df["year_month"].isin(prior)].groupby(by, as_index=False)[value]
           .sum().rename(columns={value: "prior_12m"}))

    out = cur.merge(pri, on=by, how="outer").fillna(0.0)
    out["delta_abs"] = out["current_12m"] - out["prior_12m"]
    out["delta_pct"] = out["delta_abs"] / out["prior_12m"].replace(0, np.nan)
    out["share_pct"] = out["current_12m"] / out["current_12m"].sum()
    return out.sort_values("current_12m", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Price / volume bridge
# ---------------------------------------------------------------------------
def price_volume_bridge(df: pd.DataFrame, by: list[str],
                        months: int = 12) -> pd.DataFrame:
    """Decompose the year-on-year revenue movement into its drivers.

    For every element of ``by`` the change in revenue is split into::

        dR = P0 * dV        volume effect  (more or less traffic at old prices)
           + V0 * dP        price effect   (rate erosion or price repair)
           + dV * dP        joint effect   (interaction of the two)

    Elements present in only one of the two periods are reported separately as
    new business or lost business, so the bridge always adds back to the total
    revenue movement.
    """
    all_months = sorted(df["year_month"].unique())
    cur_months, pri_months = all_months[-months:], all_months[-2 * months:-months]

    def slice_agg(ms: list[str]) -> pd.DataFrame:
        sub = df[df["year_month"].isin(ms)]
        agg = sub.groupby(by, as_index=False)[["revenue_eur", "volume_units"]].sum()
        agg["price"] = agg["revenue_eur"] / agg["volume_units"].replace(0, np.nan)
        return agg

    cur, pri = slice_agg(cur_months), slice_agg(pri_months)
    merged = cur.merge(pri, on=by, how="outer", suffixes=("_cur", "_pri"))

    both = merged["volume_units_cur"].notna() & merged["volume_units_pri"].notna()
    v0 = merged["volume_units_pri"].fillna(0.0)
    v1 = merged["volume_units_cur"].fillna(0.0)
    p0 = merged["price_pri"]
    p1 = merged["price_cur"]

    dv, dp = v1 - v0, (p1 - p0)

    out = merged[by].copy()
    out["revenue_prior"] = merged["revenue_eur_pri"].fillna(0.0)
    out["revenue_current"] = merged["revenue_eur_cur"].fillna(0.0)
    out["revenue_delta"] = out["revenue_current"] - out["revenue_prior"]

    out["volume_effect"] = np.where(both, p0.fillna(0.0) * dv, 0.0)
    out["price_effect"] = np.where(both, v0 * dp.fillna(0.0), 0.0)
    out["joint_effect"] = np.where(both, dv * dp.fillna(0.0), 0.0)
    out["new_business"] = np.where(~both & (out["revenue_prior"] == 0),
                                   out["revenue_current"], 0.0)
    out["lost_business"] = np.where(~both & (out["revenue_current"] == 0),
                                    -out["revenue_prior"], 0.0)

    effects = ["volume_effect", "price_effect", "joint_effect",
               "new_business", "lost_business"]
    out["unexplained"] = out["revenue_delta"] - out[effects].sum(axis=1)
    return out.sort_values("revenue_delta").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Portfolio structure
# ---------------------------------------------------------------------------
def concentration(df: pd.DataFrame, by: str = "customer_id",
                  value: str = "revenue_eur", months: int = 12) -> dict[str, float]:
    """Customer concentration over the trailing window (share + HHI)."""
    all_months = sorted(df["year_month"].unique())
    sub = df[df["year_month"].isin(all_months[-months:])]
    totals = sub.groupby(by)[value].sum().sort_values(ascending=False)
    total = float(totals.sum())
    if total <= 0:
        return {"top_1_share": np.nan, "top_10_share": np.nan, "hhi": np.nan, "n": 0}
    shares = totals / total
    return {
        "top_1_share": float(shares.iloc[0]),
        "top_10_share": float(shares.head(10).sum()),
        "hhi": float((shares ** 2).sum() * 10_000),
        "n": int(len(totals)),
    }


def net_revenue_retention(df: pd.DataFrame, months: int = 12) -> float:
    """Revenue this year from customers active last year, over their prior revenue."""
    all_months = sorted(df["year_month"].unique())
    cur_ms, pri_ms = all_months[-months:], all_months[-2 * months:-months]
    pri = df[df["year_month"].isin(pri_ms)].groupby("customer_id")["revenue_eur"].sum()
    cur = df[df["year_month"].isin(cur_ms)].groupby("customer_id")["revenue_eur"].sum()
    cohort = pri.index
    if pri.sum() <= 0:
        return float("nan")
    return float(cur.reindex(cohort).fillna(0.0).sum() / pri.sum())


# ---------------------------------------------------------------------------
# Headline KPI set
# ---------------------------------------------------------------------------
def headline_kpis(mart: pd.DataFrame, months: int = 12) -> pd.DataFrame:
    """The management KPI card: level, prior-year comparison and growth."""
    all_months = sorted(mart["year_month"].unique())
    cur_ms, pri_ms = all_months[-months:], all_months[-2 * months:-months]
    cur = mart[mart["year_month"].isin(cur_ms)]
    pri = mart[mart["year_month"].isin(pri_ms)]

    def block(sub: pd.DataFrame) -> dict[str, float]:
        rev = float(sub["revenue_eur"].sum())
        mar = float(sub["margin_eur"].sum())
        return {
            "Revenue (EUR m)": rev / 1e6,
            "Gross margin (EUR m)": mar / 1e6,
            "Gross margin %": (mar / rev * 100) if rev else np.nan,
            "Active markets": float(sub["country_code"].nunique()),
            "Active products": float(sub["product_id"].nunique()),
        }

    cur_b, pri_b = block(cur), block(pri)
    first_year = mart[mart["year_month"] <= all_months[11]]["revenue_eur"].sum()
    years = (len(all_months) - 12) / 12.0

    rows = []
    for name in cur_b:
        c, p = cur_b[name], pri_b[name]
        delta = c - p
        rows.append({
            "kpi": name,
            "current_12m": c,
            "prior_12m": p,
            "delta_abs": delta,
            "delta_pct": (delta / p) if (p not in (0, np.nan) and not pd.isna(p)) else np.nan,
        })

    rows.append({
        "kpi": "Revenue CAGR since start",
        "current_12m": cagr(float(first_year), float(cur["revenue_eur"].sum()), years),
        "prior_12m": np.nan, "delta_abs": np.nan, "delta_pct": np.nan,
    })
    # Concentration is only meaningful on a mart that carries the customer key.
    if "customer_id" in mart.columns:
        conc = concentration(mart)
        rows.append({"kpi": "Top-10 customer share",
                     "current_12m": conc["top_10_share"],
                     "prior_12m": np.nan, "delta_abs": np.nan, "delta_pct": np.nan})
    return pd.DataFrame(rows)
