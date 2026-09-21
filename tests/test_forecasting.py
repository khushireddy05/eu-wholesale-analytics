"""Forecasting: feature integrity, metric correctness and the backtest contract.

The leakage tests matter most. A forecast that quietly sees the future scores
beautifully in backtest and fails in production.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eu_wholesale.forecasting import backtest as bt
from eu_wholesale.forecasting import models as fm
from eu_wholesale.forecasting.dataset import (build_panel, build_supervised,
                                              feature_columns, is_log_scale)
from eu_wholesale.forecasting.run import combine_actual_forecast, run_forecast
from eu_wholesale.forecasting.scenarios import build_scenarios, scenario_summary


@pytest.fixture(scope="module")
def panel(model):
    return build_panel(model["mart_market"], "revenue_eur", future_months=3)


@pytest.fixture(scope="module")
def supervised(panel):
    return build_supervised(panel, "revenue_eur", horizon=3, lags=[1, 2, 12],
                            windows=[3, 12])


def test_panel_is_dense_and_carries_the_forecast_window(panel, model):
    mart = model["mart_market"]
    n_series = mart[["country_code", "product_id"]].drop_duplicates().shape[0]
    n_months = mart["year_month"].nunique() + 3
    assert len(panel) == n_series * n_months
    assert int(panel["is_future"].sum()) == n_series * 3


def test_lag_features_look_backwards_only(panel, supervised):
    """lag_k at an origin must equal the series value k months before it."""
    lookup = panel.set_index(["country_code", "product_id", "year_month"])["revenue_eur"]
    sample = supervised[supervised["lag_1"].notna()].sample(40, random_state=0)
    for _, row in sample.iterrows():
        origin = pd.Period(row["origin_year_month"], freq="M")
        for lag in (1, 2, 12):
            expected = lookup.get((row["country_code"], row["product_id"],
                                   str(origin - lag)))
            if expected is None or np.isnan(expected):
                continue
            assert row[f"lag_{lag}"] == pytest.approx(expected), \
                f"lag_{lag} does not match the panel at origin {origin}"


def test_seasonal_naive_feature_points_twelve_months_before_the_target(panel, supervised):
    lookup = panel.set_index(["country_code", "product_id", "year_month"])["revenue_eur"]
    sample = supervised[supervised["snaive"].notna()].sample(40, random_state=1)
    for _, row in sample.iterrows():
        target = pd.Period(row["target_year_month"], freq="M")
        expected = lookup.get((row["country_code"], row["product_id"], str(target - 12)))
        if expected is None or np.isnan(expected):
            continue
        assert row["snaive"] == pytest.approx(expected)


def test_target_is_exactly_h_months_after_the_origin(supervised):
    rows = supervised[supervised["target_year_month"].notna()]
    origin = pd.PeriodIndex(rows["origin_year_month"], freq="M")
    target = pd.PeriodIndex(rows["target_year_month"], freq="M")
    assert ((target - origin).n if hasattr(target - origin, "n") else
            np.array([(t - o).n for t, o in zip(target, origin)])).tolist() == \
        rows["horizon"].tolist()


def test_no_target_column_leaks_into_the_feature_set(supervised):
    numeric, categorical = feature_columns(supervised, "revenue_eur")
    for banned in ("y", "revenue_eur", "target_year_month", "volume_units",
                   "active_customers", "is_future"):
        assert banned not in numeric and banned not in categorical


def test_log_scale_classification_covers_magnitude_features_only():
    assert is_log_scale("lag_1") and is_log_scale("roll_mean_12") and is_log_scale("snaive")
    # Signed and ratio features must not be log transformed.
    assert not is_log_scale("gdp_growth_yoy")
    assert not is_log_scale("cpi_yoy")
    assert not is_log_scale("month_sin")
    assert not is_log_scale("horizon")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def test_metrics_are_zero_for_a_perfect_forecast():
    y = np.array([100.0, 200.0, 300.0])
    assert fm.mae(y, y) == 0.0
    assert fm.rmse(y, y) == 0.0
    assert fm.wape(y, y) == 0.0
    assert fm.mape(y, y) == 0.0
    assert fm.bias_pct(y, y) == 0.0


def test_wape_matches_its_definition():
    y = np.array([100.0, 100.0])
    yhat = np.array([110.0, 80.0])
    # |10| + |20| = 30 over 200 = 15%
    assert fm.wape(y, yhat) == pytest.approx(15.0)


def test_bias_is_signed():
    y = np.array([100.0, 100.0])
    assert fm.bias_pct(y, np.array([110.0, 110.0])) == pytest.approx(10.0)
    assert fm.bias_pct(y, np.array([90.0, 90.0])) == pytest.approx(-10.0)


def test_mape_ignores_zero_actuals():
    y = np.array([0.0, 100.0])
    yhat = np.array([50.0, 110.0])
    assert fm.mape(y, yhat) == pytest.approx(10.0)


def test_seasonal_naive_returns_the_snaive_column():
    X = pd.DataFrame({"snaive": [5.0, np.nan], "lag_1": [1.0, 2.0]})
    pred = fm.SeasonalNaive().fit(X).predict(X)
    assert pred[0] == 5.0
    assert pred[1] == 2.0, "should fall back to lag_1 when snaive is missing"


# ---------------------------------------------------------------------------
# Backtest and end-to-end
# ---------------------------------------------------------------------------
def test_origins_leave_a_full_horizon_to_score(small_config):
    months = small_config.history_months
    origins = bt.make_origins(months, horizon=3, folds=2, step=3, min_train=24)
    assert origins
    for origin in origins:
        remaining = len(months) - list(months.astype(str)).index(origin) - 1
        assert remaining >= 3


def test_backtest_never_trains_on_the_evaluation_window(supervised, small_config):
    """Training rows must all have target months at or before the origin."""
    origins = bt.make_origins(small_config.history_months, 3, 2, 3, 24)
    origin = origins[0]
    train = supervised[supervised["target_year_month"].notna()
                       & (supervised["target_year_month"] <= origin)
                       & supervised["y"].notna()]
    assert (train["target_year_month"] <= origin).all()
    test = supervised[(supervised["origin_year_month"] == origin)
                      & (supervised["target_year_month"] > origin)]
    assert (test["target_year_month"] > origin).all()
    assert not train.empty and not test.empty


@pytest.fixture(scope="module")
def forecast_result(small_config, model):
    return run_forecast(small_config, model["mart_market"])


def test_forecast_covers_every_series_and_month(forecast_result, small_config, model):
    fc = forecast_result.forecast
    mart = model["mart_market"]
    n_series = mart[["country_code", "product_id"]].drop_duplicates().shape[0]
    assert len(fc) == n_series * small_config.horizon
    assert sorted(fc["year_month"].unique()) == list(small_config.forecast_months.astype(str))


def test_forecast_values_are_non_negative_and_bracketed(forecast_result):
    fc = forecast_result.forecast
    assert (fc["forecast_eur"] >= 0).all()
    assert (fc["forecast_lo_eur"] <= fc["forecast_eur"]).all()
    assert (fc["forecast_hi_eur"] >= fc["forecast_eur"]).all()


def test_every_candidate_model_is_scored(forecast_result, small_config):
    scored = set(forecast_result.metrics_overall["model"])
    assert scored == set(small_config.forecasting["models"])
    assert forecast_result.champion in scored


def test_champion_has_the_best_selection_metric(forecast_result, small_config):
    metric = small_config.forecasting["selection_metric"]
    metrics = forecast_result.metrics_overall.set_index("model")
    best = metrics[metric].idxmin()
    assert forecast_result.champion == best


def test_prediction_intervals_have_positive_width_at_every_horizon(forecast_result):
    fc = forecast_result.forecast
    width = ((fc["forecast_hi_eur"] - fc["forecast_lo_eur"]) / fc["forecast_eur"])
    assert (width.groupby(fc["horizon"]).mean() > 0).all()


def test_intervals_widen_when_measured_error_widens():
    """The interval mechanism itself: quantiles are read off realised error.

    Monotonic widening is a property of the data, not something the code
    imposes - so it is asserted here against errors that are constructed to
    grow with horizon, rather than against a two-fold backtest where the
    empirical quantiles are necessarily noisy.
    """
    rng = np.random.default_rng(0)
    rows = []
    for h in (1, 6, 12):
        spread = 0.02 * h          # error grows with the horizon
        for _ in range(400):
            pred = 100.0
            rows.append({"model": "m", "horizon": h, "y_pred": pred,
                         "y": pred * (1 + rng.normal(0, spread))})
    quantiles = bt.residual_quantiles(pd.DataFrame(rows), "m")
    width = (quantiles["hi"] - quantiles["lo"]).to_numpy()
    assert width[0] < width[1] < width[2]
    assert (quantiles["lo"] <= 1.0).all() and (quantiles["hi"] >= 1.0).all()


def test_actual_and_forecast_combine_into_one_continuous_series(
        forecast_result, model, small_config):
    combined = combine_actual_forecast(model["mart_market"], forecast_result.forecast)
    assert set(combined["measure"]) == {"Actual", "Forecast"}
    months = sorted(combined["year_month"].unique())
    expected = list(small_config.history_months.astype(str)) + \
        list(small_config.forecast_months.astype(str))
    assert months == sorted(expected)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def test_scenarios_order_and_reconcile(small_config, forecast_result, model):
    scenarios = build_scenarios(small_config, forecast_result.forecast)
    summary = scenario_summary(scenarios, model["mart_market"])
    totals = summary.set_index("scenario")["next_12m_eur"]
    assert totals["Downside"] < totals["Baseline"] < totals["Upside"]
    # Baseline applies no driver adjustment, so it equals the raw forecast.
    assert totals["Baseline"] == pytest.approx(
        forecast_result.forecast["forecast_eur"].sum())


def test_scenario_effects_ramp_with_horizon(small_config, forecast_result):
    scenarios = build_scenarios(small_config, forecast_result.forecast)
    up = scenarios[scenarios["scenario"] == "Upside"]
    by_h = up.groupby("horizon")["driver_factor"].mean()
    assert by_h.is_monotonic_increasing
    assert by_h.iloc[0] > 1.0
