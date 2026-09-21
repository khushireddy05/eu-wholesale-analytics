"""Forecast pipeline orchestration.

Runs the full sequence: panel construction, supervised framing, model
comparison by rolling-origin backtest, champion selection, refit on the
complete history and forward projection with empirical prediction intervals.

Forecasts are produced at the market x product grain and aggregated upwards.
Because every higher-level view is a bottom-up sum of the same base forecast,
the country view, the product view and the group total always reconcile.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import Config
from . import backtest as bt
from .dataset import build_panel, build_supervised, feature_columns
from .models import DirectMultiHorizon


@dataclass
class ForecastResult:
    forecast: pd.DataFrame          # base-grain forward forecast with intervals
    predictions: pd.DataFrame       # backtest predictions, all models
    metrics_overall: pd.DataFrame   # accuracy by model
    metrics_horizon: pd.DataFrame   # champion accuracy by horizon
    metrics_product: pd.DataFrame   # champion accuracy by product
    metrics_country: pd.DataFrame   # champion accuracy by country
    champion: str
    origins: list[str]

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "fact_forecast": self.forecast,
            "backtest_predictions": self.predictions,
            "accuracy_by_model": self.metrics_overall,
            "accuracy_by_horizon": self.metrics_horizon,
            "accuracy_by_product": self.metrics_product,
            "accuracy_by_country": self.metrics_country,
        }


def run_forecast(cfg: Config, mart: pd.DataFrame) -> ForecastResult:
    fc = cfg.forecasting
    target = fc["target"]
    horizon = cfg.horizon
    keys = tuple(fc["grain"])

    panel = build_panel(mart, target=target, keys=keys, future_months=horizon)
    sup = build_supervised(panel, target=target, horizon=horizon,
                           lags=list(fc["lags"]), windows=list(fc["rolling_windows"]),
                           keys=keys)
    numeric, categorical = feature_columns(sup, target)

    origins = bt.make_origins(cfg.history_months, horizon,
                              folds=int(fc["backtest_folds"]),
                              step=int(fc["backtest_step"]),
                              min_train=int(fc["min_train_months"]))

    predictions, metrics_overall = bt.run_backtest(
        sup, numeric, categorical, list(fc["models"]), origins, horizon, seed=cfg.seed
    )
    champion = bt.select_champion(metrics_overall, metric=fc["selection_metric"])

    # ---- refit on the complete history and project forward ---------------
    train_all = sup[sup["y"].notna()]
    final = DirectMultiHorizon(champion, numeric, categorical, horizon, cfg.seed).fit(train_all)

    last_origin = str(cfg.history_end)
    future = sup[(sup["origin_year_month"] == last_origin) & sup["y"].isna()].copy()
    future = future[future["target_month_no"].notna()]
    future["forecast_eur"] = final.predict(future)

    intervals = bt.residual_quantiles(predictions, champion)
    future = future.merge(intervals, on="horizon", how="left")
    future["forecast_lo_eur"] = future["forecast_eur"] * future["lo"].fillna(0.85)
    future["forecast_hi_eur"] = future["forecast_eur"] * future["hi"].fillna(1.15)

    forecast = (future[list(keys) + ["target_year_month", "horizon", "forecast_eur",
                                     "forecast_lo_eur", "forecast_hi_eur"]]
                .rename(columns={"target_year_month": "year_month"})
                .sort_values(list(keys) + ["year_month"])
                .reset_index(drop=True))
    forecast["model"] = champion
    forecast["scenario"] = "Baseline"

    return ForecastResult(
        forecast=forecast,
        predictions=predictions,
        metrics_overall=metrics_overall,
        metrics_horizon=bt.accuracy_by(predictions, champion, "horizon"),
        metrics_product=bt.accuracy_by(predictions, champion, "product_id"),
        metrics_country=bt.accuracy_by(predictions, champion, "country_code"),
        champion=champion,
        origins=origins,
    )


def combine_actual_forecast(mart: pd.DataFrame, forecast: pd.DataFrame,
                            keys: tuple[str, ...] = ("country_code", "product_id"),
                            target: str = "revenue_eur") -> pd.DataFrame:
    """Single continuous series of actuals followed by forecast.

    This is the table the trend charts and the Power BI model read: one row per
    month per series, flagged so a visual can style history and projection
    differently without any join logic.
    """
    actual = (mart.groupby(list(keys) + ["year_month"], as_index=False)[target].sum()
                  .rename(columns={target: "value_eur"}))
    actual["measure"] = "Actual"
    actual["value_lo_eur"] = actual["value_eur"]
    actual["value_hi_eur"] = actual["value_eur"]

    fc = forecast.rename(columns={"forecast_eur": "value_eur",
                                  "forecast_lo_eur": "value_lo_eur",
                                  "forecast_hi_eur": "value_hi_eur"})[
        list(keys) + ["year_month", "value_eur", "value_lo_eur", "value_hi_eur"]]
    fc["measure"] = "Forecast"

    out = pd.concat([actual, fc], ignore_index=True)
    return out.sort_values(list(keys) + ["year_month"]).reset_index(drop=True)
