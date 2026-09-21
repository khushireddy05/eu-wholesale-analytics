"""Forecasting models and evaluation metrics.

Four candidates are compared on identical data, from a naive benchmark up to a
gradient-boosted ensemble. A model only earns its place if it beats the
benchmark on the backtest - which is the point of including it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import Pipeline

from .dataset import is_log_scale
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def mae(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.mean(np.abs(y - yhat)))


def rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - yhat) ** 2)))


def mape(y: np.ndarray, yhat: np.ndarray) -> float:
    """Mean absolute percentage error, computed only where the actual is non-zero."""
    mask = np.abs(y) > 1e-9
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y[mask] - yhat[mask]) / y[mask])) * 100)


def smape(y: np.ndarray, yhat: np.ndarray) -> float:
    denom = (np.abs(y) + np.abs(yhat)) / 2.0
    mask = denom > 1e-9
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs(y[mask] - yhat[mask]) / denom[mask]) * 100)


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    """Weighted absolute percentage error - the volume-weighted accuracy measure.

    Preferred over MAPE for revenue series: it is not distorted by small
    denominators and it aggregates meaningfully across markets of different size.
    """
    denom = float(np.sum(np.abs(y)))
    if denom <= 1e-9:
        return float("nan")
    return float(np.sum(np.abs(y - yhat)) / denom * 100)


def bias_pct(y: np.ndarray, yhat: np.ndarray) -> float:
    """Signed forecast bias: positive means the forecast runs high."""
    denom = float(np.sum(np.abs(y)))
    if denom <= 1e-9:
        return float("nan")
    return float(np.sum(yhat - y) / denom * 100)


METRICS = {"mae": mae, "rmse": rmse, "mape": mape,
           "smape": smape, "wape": wape, "bias_pct": bias_pct}


def score(y: np.ndarray, yhat: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    return {name: fn(y, yhat) for name, fn in METRICS.items()}


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------
class SeasonalNaive(BaseEstimator, RegressorMixin):
    """Predict the value from the same month one year earlier.

    The reference benchmark for strongly seasonal telecom traffic. It is
    implemented as an estimator so it runs through exactly the same backtest
    harness as the learned models.
    """

    def __init__(self, column: str = "snaive", fallback: str = "lag_1"):
        self.column = column
        self.fallback = fallback

    def fit(self, X: pd.DataFrame, y=None):  # noqa: D102 - trivial
        self.fitted_ = True
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        pred = X[self.column].astype(float).to_numpy(copy=True)
        if self.fallback in X.columns:
            fb = X[self.fallback].astype(float).to_numpy()
            pred = np.where(np.isnan(pred), fb, pred)
        return np.nan_to_num(pred, nan=0.0)


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------
def _safe_log1p(x):
    """log1p with a floor at zero - level features are non-negative by nature."""
    return np.log1p(np.clip(x, 0.0, None))


def _preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    log_cols = [c for c in numeric if is_log_scale(c)]
    lin_cols = [c for c in numeric if not is_log_scale(c)]

    # Magnitude features go through logs so that a linear model in log-target
    # space expresses the multiplicative structure of the series (a 10% move in
    # last month's revenue implies a 10% move in the forecast, in any market).
    log_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("log", FunctionTransformer(_safe_log1p, feature_names_out="one-to-one")),
        ("scale", StandardScaler()),
    ])
    numeric_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return ColumnTransformer([
        ("log", log_pipe, log_cols),
        ("num", numeric_pipe, lin_cols),
        ("cat", categorical_pipe, categorical),
    ], remainder="drop")


def _log_target(estimator: Any) -> TransformedTargetRegressor:
    """Fit on log1p(revenue).

    Wholesale revenue series are strictly positive and behave multiplicatively
    (growth rates, price erosion), so errors are proportional rather than
    additive. Modelling the log makes the residuals homoscedastic and stops
    large markets from dominating the loss.
    """
    return TransformedTargetRegressor(regressor=estimator,
                                      func=np.log1p, inverse_func=np.expm1)


def build_model(name: str, numeric: list[str], categorical: list[str],
                seed: int = 0) -> Any:
    """Instantiate a named candidate model."""
    if name == "seasonal_naive":
        return SeasonalNaive()

    if name == "ridge":
        est = Ridge(alpha=3.0, random_state=seed)
    elif name == "elastic_net":
        est = ElasticNet(alpha=0.002, l1_ratio=0.35, max_iter=8000, random_state=seed)
    elif name == "gradient_boosting":
        est = HistGradientBoostingRegressor(
            max_iter=320, learning_rate=0.06, max_depth=6,
            min_samples_leaf=24, l2_regularization=0.9, random_state=seed,
        )
    else:
        raise ValueError(f"Unknown model '{name}'")

    return Pipeline([
        ("prep", _preprocessor(numeric, categorical)),
        ("model", _log_target(est)),
    ])


@dataclass
class DirectMultiHorizon:
    """Fits one estimator per forecast horizon.

    Direct multi-horizon forecasting avoids the error compounding of recursive
    strategies: the h-step model is trained on h-step errors, so a bad one-step
    prediction is never fed back in as an input.
    """

    name: str
    numeric: list[str]
    categorical: list[str]
    horizon: int
    seed: int = 0
    models_: dict[int, Any] = field(default_factory=dict, repr=False)

    def fit(self, sup: pd.DataFrame) -> "DirectMultiHorizon":
        for h in range(1, self.horizon + 1):
            block = sup[(sup["horizon"] == h) & sup["y"].notna()]
            if block.empty:
                continue
            est = build_model(self.name, self.numeric, self.categorical, self.seed)
            X = block[self.numeric + self.categorical]
            est = clone(est) if hasattr(est, "get_params") else est
            est.fit(X, block["y"].to_numpy(dtype=float))
            self.models_[h] = est
        return self

    def predict(self, sup: pd.DataFrame) -> np.ndarray:
        out = np.full(len(sup), np.nan)
        for h, est in self.models_.items():
            mask = (sup["horizon"] == h).to_numpy()
            if not mask.any():
                continue
            X = sup.loc[mask, self.numeric + self.categorical]
            out[mask] = est.predict(X)
        # Revenue cannot be negative.
        return np.clip(np.nan_to_num(out, nan=0.0), 0.0, None)
