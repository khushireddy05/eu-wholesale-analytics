"""KPI arithmetic - the calculations every downstream view depends on."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eu_wholesale import kpis


def test_aggregate_recomputes_ratios_rather_than_averaging(model):
    mart = model["mart_market"]
    out = kpis.aggregate(mart, by=["product_id"])
    for _, r in out.iterrows():
        assert r["margin_pct"] == pytest.approx(r["margin_eur"] / r["revenue_eur"])
        assert r["unit_price_eur"] == pytest.approx(r["revenue_eur"] / r["volume_units"])


def test_cagr_matches_closed_form():
    assert kpis.cagr(100.0, 121.0, 2.0) == pytest.approx(0.10)
    assert np.isnan(kpis.cagr(0.0, 100.0, 2.0))
    assert np.isnan(kpis.cagr(100.0, 200.0, 0.0))


def test_yoy_table_shares_sum_to_one(model):
    table = kpis.yoy_table(model["mart_market"], "country_code")
    assert table["share_pct"].sum() == pytest.approx(1.0)
    assert (table["current_12m"] >= 0).all()


def test_price_volume_bridge_reconciles_exactly(model):
    """The decomposition must add back to the total revenue movement."""
    bridge = kpis.price_volume_bridge(model["mart_market"], ["product_id"])
    effects = bridge[["volume_effect", "price_effect", "joint_effect",
                      "new_business", "lost_business"]].sum(axis=1)
    residual = (bridge["revenue_delta"] - effects).abs()
    assert residual.max() < 1.0, "bridge leaves an unexplained residual"
    assert bridge["unexplained"].abs().max() < 1.0


def test_bridge_isolates_a_pure_price_move():
    """With volume held flat, the whole movement must land on the price effect."""
    months_prior = [f"2024-{m:02d}" for m in range(1, 13)]
    months_cur = [f"2025-{m:02d}" for m in range(1, 13)]
    rows = []
    for ym in months_prior:
        rows.append({"year_month": ym, "product_id": "P01",
                     "revenue_eur": 100.0, "volume_units": 10.0})
    for ym in months_cur:
        rows.append({"year_month": ym, "product_id": "P01",
                     "revenue_eur": 120.0, "volume_units": 10.0})
    df = pd.DataFrame(rows)

    bridge = kpis.price_volume_bridge(df, ["product_id"])
    row = bridge.iloc[0]
    assert row["revenue_delta"] == pytest.approx(240.0)
    assert row["volume_effect"] == pytest.approx(0.0)
    assert row["price_effect"] == pytest.approx(240.0)
    assert row["joint_effect"] == pytest.approx(0.0)


def test_bridge_isolates_a_pure_volume_move():
    rows = []
    for ym in [f"2024-{m:02d}" for m in range(1, 13)]:
        rows.append({"year_month": ym, "product_id": "P01",
                     "revenue_eur": 100.0, "volume_units": 10.0})
    for ym in [f"2025-{m:02d}" for m in range(1, 13)]:
        rows.append({"year_month": ym, "product_id": "P01",
                     "revenue_eur": 150.0, "volume_units": 15.0})
    bridge = kpis.price_volume_bridge(pd.DataFrame(rows), ["product_id"])
    row = bridge.iloc[0]
    assert row["price_effect"] == pytest.approx(0.0)
    assert row["volume_effect"] == pytest.approx(row["revenue_delta"])


def test_concentration_bounds(model):
    conc = kpis.concentration(model["mart_customer"])
    assert 0.0 < conc["top_1_share"] <= conc["top_10_share"] <= 1.0
    assert 0.0 < conc["hhi"] <= 10_000.0
    assert conc["n"] > 0


def test_net_revenue_retention_is_positive(model):
    nrr = kpis.net_revenue_retention(model["mart_customer"])
    assert 0.0 < nrr < 3.0


def test_monthly_series_fills_gaps_with_zero(model):
    mart = model["mart_market"]
    series = kpis.monthly_series(mart, "revenue_eur", by=["country_code", "product_id"])
    n_series = mart[["country_code", "product_id"]].drop_duplicates().shape[0]
    assert len(series) == n_series * mart["year_month"].nunique()
    assert series["revenue_eur"].notna().all()
