"""Scenario construction on top of the champion forecast.

Scenarios are deliberately *not* re-fitted models. They are explicit,
documented adjustments to two commercial drivers - realised price and traffic
volume - applied to the statistical baseline. That separation keeps the
question "what does the data say?" apart from "what if the market moves?", and
means every scenario number can be traced to a stated assumption.

The effect of a scenario at horizon ``h`` months is::

    factor(h) = (1 + price_effect_pa  * w) ** (h / 12)
              * (1 + volume_effect_pa * w) ** (h / 12)

where ``w`` is an optional per-product weight. Effects therefore ramp in
gradually rather than stepping on day one, which is how commercial changes
actually land.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config

SCENARIO_ORDER = ("Downside", "Baseline", "Upside")


def _scenario_factor(horizon: pd.Series, price_pa: float, volume_pa: float,
                     weight: pd.Series) -> pd.Series:
    years = horizon / 12.0
    price = (1.0 + price_pa * weight) ** years
    volume = (1.0 + volume_pa * weight) ** years
    return price * volume


def build_scenarios(cfg: Config, forecast: pd.DataFrame) -> pd.DataFrame:
    """Expand the baseline forecast into the full scenario set."""
    frames: list[pd.DataFrame] = []

    for key, spec in cfg.scenarios.items():
        label = spec.get("label", key.title())
        overrides = spec.get("product_multipliers", {}) or {}
        weight = forecast["product_id"].map(overrides).fillna(1.0).astype(float)

        factor = _scenario_factor(
            forecast["horizon"], float(spec.get("price_effect_pa", 0.0)),
            float(spec.get("volume_effect_pa", 0.0)), weight,
        )

        block = forecast.copy()
        block["scenario"] = label
        block["scenario_key"] = key
        block["scenario_description"] = spec.get("description", "")
        block["driver_factor"] = factor
        for col in ("forecast_eur", "forecast_lo_eur", "forecast_hi_eur"):
            block[col] = block[col] * factor
        frames.append(block)

    out = pd.concat(frames, ignore_index=True)
    out["scenario"] = pd.Categorical(out["scenario"], categories=list(SCENARIO_ORDER),
                                     ordered=True)
    return out.sort_values(["scenario", "country_code", "product_id", "year_month"]
                           ).reset_index(drop=True)


def scenario_summary(scenarios: pd.DataFrame, mart: pd.DataFrame,
                     by: list[str] | None = None) -> pd.DataFrame:
    """Compare each scenario's next-12-month total against the last 12 actuals."""
    by = by or []
    months = sorted(mart["year_month"].unique())
    last_12 = months[-12:]
    base = (mart[mart["year_month"].isin(last_12)]
            .groupby(by, as_index=False)["revenue_eur"].sum()
            if by else
            pd.DataFrame({"revenue_eur": [mart.loc[mart["year_month"].isin(last_12),
                                                   "revenue_eur"].sum()]}))
    base = base.rename(columns={"revenue_eur": "last_12m_eur"})

    fc = (scenarios.groupby(by + ["scenario"], as_index=False, observed=True)
                   ["forecast_eur"].sum()
                   .rename(columns={"forecast_eur": "next_12m_eur"}))

    out = fc.merge(base, on=by, how="left") if by else fc.assign(
        last_12m_eur=float(base["last_12m_eur"].iloc[0]))
    out["delta_eur"] = out["next_12m_eur"] - out["last_12m_eur"]
    out["growth_pct"] = out["delta_eur"] / out["last_12m_eur"]
    return out.sort_values(by + ["scenario"]).reset_index(drop=True)


def scenario_monthly(scenarios: pd.DataFrame) -> pd.DataFrame:
    """Group-level monthly path per scenario, for the trend chart."""
    return (scenarios.groupby(["scenario", "year_month"], as_index=False, observed=True)
                     .agg(forecast_eur=("forecast_eur", "sum"),
                          forecast_lo_eur=("forecast_lo_eur", "sum"),
                          forecast_hi_eur=("forecast_hi_eur", "sum")))


def scenario_spread(summary: pd.DataFrame) -> dict[str, float]:
    """Headline spread between the extreme scenarios, in EUR and percent."""
    totals = summary.set_index("scenario")["next_12m_eur"]
    up = float(totals.get("Upside", float("nan")))
    down = float(totals.get("Downside", float("nan")))
    base = float(totals.get("Baseline", float("nan")))
    return {
        "baseline_eur": base,
        "upside_eur": up,
        "downside_eur": down,
        "spread_eur": up - down,
        "spread_pct_of_baseline": (up - down) / base if base else float("nan"),
    }
