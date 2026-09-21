"""Dataset generation: reproducibility, shape and the structural dynamics
the market model is supposed to produce."""

from __future__ import annotations

import pandas as pd
import pytest

from eu_wholesale.data.generate import generate_dataset
from eu_wholesale.data.indicators import build_market_indicators


def test_generation_is_reproducible(small_config):
    a = generate_dataset(small_config).fact_traffic
    b = generate_dataset(small_config).fact_traffic
    pd.testing.assert_frame_equal(a, b)


def test_fact_grain_is_unique(dataset):
    fact = dataset.fact_traffic
    keys = ["year_month", "customer_id", "product_id"]
    assert not fact.duplicated(subset=keys).any()


def test_measures_are_internally_consistent(dataset):
    fact = dataset.fact_traffic
    assert (fact["revenue_eur"] > 0).all()
    assert (fact["volume_units"] > 0).all()
    # margin = revenue - cost holds to rounding.
    residual = (fact["revenue_eur"] - fact["cost_eur"] - fact["margin_eur"]).abs()
    assert residual.max() < 0.05
    # cost never exceeds revenue: gross margin stays positive.
    assert (fact["cost_eur"] <= fact["revenue_eur"]).all()


def test_calendar_is_complete(small_config, dataset):
    assert dataset.fact_traffic["year_month"].nunique() == len(small_config.history_months)
    # dim_date spans history plus the forecast horizon, so forecast rows have
    # a date to join to; it must start at history_start and be gap-free.
    dim_months = list(dataset.dim_date["year_month"])
    history_months = list(small_config.history_months.astype(str))
    assert dim_months[:len(history_months)] == history_months
    assert len(dim_months) == len(history_months) + small_config.horizon
    assert pd.PeriodIndex(dim_months, freq="M").is_monotonic_increasing


def test_churned_accounts_stop_transacting(dataset):
    churned = dataset.dim_customer[dataset.dim_customer["churn_month"] != ""]
    if churned.empty:
        pytest.skip("no churn in this sample")
    fact = dataset.fact_traffic
    for _, cust in churned.iterrows():
        rows = fact[fact["customer_id"] == cust["customer_id"]]
        if rows.empty:
            continue
        # Traffic winds down over three months, so nothing survives past that.
        last = pd.Period(rows["year_month"].max(), freq="M")
        assert last <= pd.Period(cust["churn_month"], freq="M") + 3


def test_new_business_starts_at_go_live(dataset):
    new = dataset.dim_customer[dataset.dim_customer["is_new_business"]]
    if new.empty:
        pytest.skip("no new business in this sample")
    fact = dataset.fact_traffic
    for _, cust in new.iterrows():
        rows = fact[fact["customer_id"] == cust["customer_id"]]
        if rows.empty:
            continue
        assert pd.Period(rows["year_month"].min(), freq="M") >= \
            pd.Period(cust["relationship_start"], freq="M")


def test_indicator_panel_reproduces_documented_shocks(small_config):
    months = pd.period_range("2019-01", "2023-12", freq="M")
    ind = build_market_indicators(months, small_config.seed)
    de = ind[ind["country_code"] == "DE"].set_index("year_month")

    # COVID travel collapse: Q2 2020 far below the January 2019 base.
    assert de.loc["2020-05", "travel_index"] < 25
    # Recovery above pre-pandemic by late 2022.
    assert de.loc["2022-12", "travel_index"] > 95
    # 2022 inflation spike.
    assert de.loc["2022-10", "cpi_yoy"] > 8
    # Data traffic compounds strongly across the window.
    assert de.loc["2023-12", "data_traffic_index"] > 2 * de.loc["2019-01", "data_traffic_index"]


def test_roaming_collapses_during_travel_restrictions(small_config):
    cfg = small_config
    raw = cfg.raw["calendar"].copy()
    cfg.raw["calendar"]["history_start"] = "2019-01"
    cfg.raw["calendar"]["history_end"] = "2021-12"
    try:
        cfg.__dict__.pop("history_months", None)
        cfg.__dict__.pop("forecast_months", None)
        fact = generate_dataset(cfg).fact_traffic
        roaming = fact[fact["product_id"] == "P03"]
        by_month = roaming.groupby("year_month")["revenue_eur"].sum()
        assert by_month.get("2020-05", 0) < 0.5 * by_month.get("2019-05", 1)
    finally:
        cfg.raw["calendar"] = raw
        cfg.__dict__.pop("history_months", None)
        cfg.__dict__.pop("forecast_months", None)


def test_voice_declines_and_messaging_grows(dataset):
    fact = dataset.fact_traffic.copy()
    fact["year"] = fact["year_month"].str[:4]
    annual = fact.pivot_table(index="product_id", columns="year",
                              values="revenue_eur", aggfunc="sum")
    years = sorted(annual.columns)
    first, last = years[0], years[-1]
    assert annual.loc["P01", last] < annual.loc["P01", first], "voice should decline"
    assert annual.loc["P02", last] > annual.loc["P02", first], "A2P should grow"
