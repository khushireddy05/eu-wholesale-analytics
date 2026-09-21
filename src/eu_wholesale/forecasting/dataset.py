"""Supervised learning frame construction for time-series forecasting.

The forecasting problem is framed as *direct multi-horizon* regression: for
every forecast origin ``t`` and horizon ``h`` a row is built whose features are
strictly knowable at ``t`` and whose target is the value at ``t + h``. One
model is fitted per horizon.

Two properties matter and are enforced here:

1. **No leakage.** Every feature is a lag, a rolling statistic ending at the
   origin, or a calendar attribute of the target month. Indicator values are
   taken at the origin, never at the target month.
2. **A strong baseline inside the feature set.** ``snaive`` (the value twelve
   months before the target month) is always knowable at the origin for
   ``h <= 12`` and is supplied as a feature, so the learners start from the
   seasonal-naive benchmark rather than having to rediscover it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SERIES_KEYS = ("country_code", "product_id")

# Indicator columns carried from the market panel, used at their origin value.
INDICATOR_COLS = (
    "gdp_growth_yoy", "cpi_yoy", "data_traffic_index", "ott_substitution_index",
    "travel_index", "ecommerce_index", "price_pressure_index",
)

CATEGORICAL_FEATURES = ("country_code", "product_id", "product_family",
                        "region", "lifecycle_stage", "market_maturity")


def build_panel(mart: pd.DataFrame, target: str,
                keys: tuple[str, ...] = SERIES_KEYS,
                future_months: int = 0) -> pd.DataFrame:
    """Dense monthly panel at the series grain, with attributes and indicators.

    ``future_months`` appends empty rows beyond the end of history. They carry
    no target value - they exist so that the supervised frame can name the
    months being forecast, and so the seasonal-naive reference for those months
    (which is always inside history for h <= 12) can be looked up.
    """
    months = sorted(mart["year_month"].unique())
    series = mart[list(keys)].drop_duplicates()

    measures = (mart.groupby(list(keys) + ["year_month"], as_index=False)
                    .agg(**{target: (target, "sum"),
                            "volume_units": ("volume_units", "sum"),
                            "active_customers": ("active_customers", "sum")}))

    grid = series.merge(pd.DataFrame({"year_month": months}), how="cross")
    panel = grid.merge(measures, on=list(keys) + ["year_month"], how="left")
    panel[[target, "volume_units", "active_customers"]] = (
        panel[[target, "volume_units", "active_customers"]].fillna(0.0)
    )

    # Static series attributes.
    attrs = ["country_code", "product_id", "product_family", "region",
             "lifecycle_stage", "market_maturity", "demand_index",
             "price_level_index", "gdp_per_capita_keur"]
    attrs = [c for c in attrs if c in mart.columns]
    static = mart[attrs].drop_duplicates(subset=list(keys))
    panel = panel.merge(static, on=list(keys), how="left")

    # Country x month indicators.
    ind_cols = [c for c in INDICATOR_COLS if c in mart.columns]
    if ind_cols:
        ind = (mart[["country_code", "year_month"] + ind_cols]
               .drop_duplicates(subset=["country_code", "year_month"]))
        panel = panel.merge(ind, on=["country_code", "year_month"], how="left")

    panel["is_future"] = False

    if future_months > 0:
        last = pd.Period(months[-1], freq="M")
        future = pd.period_range(last + 1, periods=future_months, freq="M").astype(str)
        tail = (series.merge(pd.DataFrame({"year_month": list(future)}), how="cross")
                      .merge(static, on=list(keys), how="left"))
        tail[target] = np.nan
        tail["is_future"] = True
        panel = pd.concat([panel, tail], ignore_index=True)

    panel["t"] = pd.PeriodIndex(panel["year_month"], freq="M").astype("int64")
    panel["t"] -= panel["t"].min()
    return panel.sort_values(list(keys) + ["year_month"]).reset_index(drop=True)


def _series_features(g: pd.DataFrame, target: str, lags: list[int],
                     windows: list[int]) -> pd.DataFrame:
    """Origin-time features for one series (all strictly backward looking)."""
    out = g.copy()
    y = out[target]
    for lag in lags:
        out[f"lag_{lag}"] = y.shift(lag)
    for w in windows:
        out[f"roll_mean_{w}"] = y.shift(1).rolling(w, min_periods=max(2, w // 2)).mean()
        out[f"roll_std_{w}"] = y.shift(1).rolling(w, min_periods=max(2, w // 2)).std()
    out["yoy_ratio"] = y.shift(1) / y.shift(13).replace(0, np.nan)
    out["mom_ratio"] = y.shift(1) / y.shift(2).replace(0, np.nan)
    out["trend_3m"] = (y.shift(1).rolling(3, min_periods=2).mean()
                       / y.shift(4).rolling(3, min_periods=2).mean().replace(0, np.nan))
    out["volume_lag_1"] = out["volume_units"].shift(1)
    out["price_lag_1"] = (out[target].shift(1)
                          / out["volume_units"].shift(1).replace(0, np.nan))
    out["customers_lag_1"] = out["active_customers"].shift(1)
    for col in INDICATOR_COLS:
        if col in out.columns:
            out[f"{col}_yoy"] = out[col] / out[col].shift(12).replace(0, np.nan) - 1.0
    return out


def build_supervised(panel: pd.DataFrame, target: str, horizon: int,
                     lags: list[int], windows: list[int],
                     keys: tuple[str, ...] = SERIES_KEYS) -> pd.DataFrame:
    """Expand the panel into (origin, horizon) training rows.

    Returns one row per series x origin x horizon with the target value at
    ``origin + h`` in column ``y``.
    """
    # Built series by series rather than with a grouped apply: the feature
    # function needs the grouping columns in its output, and an explicit loop
    # keeps that intent obvious.
    feat = pd.concat(
        [_series_features(g, target=target, lags=lags, windows=windows)
         for _, g in panel.groupby(list(keys), sort=False)],
        ignore_index=True,
    )

    frames: list[pd.DataFrame] = []
    for h in range(1, horizon + 1):
        block = feat.copy()
        grp = block.groupby(list(keys), sort=False)
        block["y"] = grp[target].shift(-h)
        block["target_year_month"] = grp["year_month"].shift(-h)
        # Seasonal-naive reference for the *target* month; knowable at origin
        # for every h <= 12 because target - 12 months <= origin.
        block["snaive"] = grp[target].shift(-h + 12)
        block["horizon"] = h
        frames.append(block)

    sup = pd.concat(frames, ignore_index=True)
    sup = sup.rename(columns={"year_month": "origin_year_month"})

    target_period = pd.PeriodIndex(sup["target_year_month"].dropna(), freq="M")
    sup.loc[sup["target_year_month"].notna(), "target_month_no"] = target_period.month
    sup["month_sin"] = np.sin(2 * np.pi * sup["target_month_no"] / 12.0)
    sup["month_cos"] = np.cos(2 * np.pi * sup["target_month_no"] / 12.0)
    return sup


# Level features measured in EUR, units or index points. They span several
# orders of magnitude across markets and enter the relationship
# multiplicatively, so the linear learners see them on a log scale (the target
# is modelled in logs too). Tree ensembles are invariant to the transform.
LOG_SCALE_PREFIXES = ("lag_", "roll_mean_", "roll_std_", "volume_lag_",
                      "price_lag_", "customers_lag_")
LOG_SCALE_NAMES = frozenset({
    "snaive", "data_traffic_index", "ott_substitution_index", "travel_index",
    "ecommerce_index", "price_pressure_index", "demand_index",
    "price_level_index", "gdp_per_capita_keur", "mobile_penetration",
})


def is_log_scale(column: str) -> bool:
    return column.startswith(LOG_SCALE_PREFIXES) or column in LOG_SCALE_NAMES


def feature_columns(sup: pd.DataFrame, target: str) -> tuple[list[str], list[str]]:
    """Split the supervised frame into numeric and categorical feature names."""
    exclude = {
        "y", "target_year_month", "origin_year_month", target,
        "volume_units", "active_customers", "is_future",
    }
    categorical = [c for c in CATEGORICAL_FEATURES if c in sup.columns]
    numeric = [
        c for c in sup.columns
        if c not in exclude and c not in categorical
        and pd.api.types.is_numeric_dtype(sup[c])
    ]
    return numeric, categorical
