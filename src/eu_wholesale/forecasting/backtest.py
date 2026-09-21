"""Rolling-origin backtesting.

Forecast quality is measured the way the business would experience it: stand
at a past month, forecast the next twelve, then compare against what actually
happened. Origins are stepped backwards through history so each model is
judged on several independent forecast rounds rather than one lucky split.

The training rule is strict - a fold may only use rows whose *target* month is
at or before the origin. Nothing about the future leaks into the fit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import DirectMultiHorizon, score

GROUP_KEYS = ("country_code", "product_id")


def make_origins(months: pd.PeriodIndex, horizon: int, folds: int,
                 step: int, min_train: int) -> list[str]:
    """Forecast origins, most recent first, that leave a full horizon to score."""
    last_scorable = len(months) - horizon - 1
    origins: list[str] = []
    for k in range(folds):
        idx = last_scorable - k * step
        if idx < min_train:
            break
        origins.append(str(months[idx]))
    return origins


def run_backtest(sup: pd.DataFrame, numeric: list[str], categorical: list[str],
                 model_names: list[str], origins: list[str], horizon: int,
                 seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate every candidate model at every origin.

    Returns ``(predictions, metrics)`` where predictions hold one row per
    model x fold x series x horizon.
    """
    preds: list[pd.DataFrame] = []

    for fold, origin in enumerate(origins, start=1):
        # Only history that had already happened at the origin.
        train = sup[sup["target_year_month"].notna()
                    & (sup["target_year_month"] <= origin)
                    & sup["y"].notna()]
        test = sup[(sup["origin_year_month"] == origin)
                   & (sup["target_year_month"] > origin)
                   & sup["y"].notna()]
        if train.empty or test.empty:
            continue

        for name in model_names:
            est = DirectMultiHorizon(name, numeric, categorical, horizon, seed).fit(train)
            yhat = est.predict(test)
            block = test[list(GROUP_KEYS) + ["origin_year_month", "target_year_month",
                                             "horizon", "y"]].copy()
            block["model"] = name
            block["fold"] = fold
            block["origin"] = origin
            block["y_pred"] = yhat
            preds.append(block)

    if not preds:
        raise RuntimeError("Backtest produced no predictions - check the calendar window.")

    predictions = pd.concat(preds, ignore_index=True)
    predictions["error"] = predictions["y_pred"] - predictions["y"]
    predictions["abs_error"] = predictions["error"].abs()
    return predictions, summarise(predictions)


def _score_frame(df: pd.DataFrame) -> pd.Series:
    return pd.Series(score(df["y"].to_numpy(), df["y_pred"].to_numpy()))


def summarise(predictions: pd.DataFrame,
              by: list[str] | None = None) -> pd.DataFrame:
    """Accuracy metrics aggregated over the requested dimensions."""
    by = by or ["model"]
    rows = []
    for keys, grp in predictions.groupby(by, sort=False):
        rec = dict(zip(by, keys if isinstance(keys, tuple) else (keys,)))
        rec.update(_score_frame(grp).to_dict())
        rec["n_obs"] = int(len(grp))
        rec["actual_eur"] = float(grp["y"].sum())
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(by).reset_index(drop=True)


def select_champion(metrics: pd.DataFrame, metric: str = "wape") -> str:
    """Pick the model with the best (lowest) score on the selection metric."""
    ranked = metrics.sort_values(metric)
    return str(ranked.iloc[0]["model"])


def residual_quantiles(predictions: pd.DataFrame, model: str,
                       lower: float = 0.10, upper: float = 0.90) -> pd.DataFrame:
    """Empirical prediction-interval multipliers by horizon.

    Intervals are derived from realised backtest errors rather than from a
    distributional assumption: for each horizon the ratio of actual to
    predicted is collected across folds and series, and its quantiles become
    the multipliers applied to the live forecast.
    """
    sub = predictions[(predictions["model"] == model) & (predictions["y_pred"] > 0)].copy()
    sub["ratio"] = sub["y"] / sub["y_pred"]
    out = (sub.groupby("horizon")["ratio"]
              .agg(lo=lambda s: s.quantile(lower),
                   hi=lambda s: s.quantile(upper),
                   median="median")
              .reset_index())
    # Guarantee the interval brackets the point forecast.
    out["lo"] = out["lo"].clip(upper=1.0)
    out["hi"] = out["hi"].clip(lower=1.0)
    return out


def accuracy_by(predictions: pd.DataFrame, model: str, dim: str) -> pd.DataFrame:
    """Champion-model accuracy sliced by one dimension, for the report pack."""
    sub = predictions[predictions["model"] == model]
    out = summarise(sub, by=[dim])
    return out.sort_values("actual_eur", ascending=False).reset_index(drop=True)
