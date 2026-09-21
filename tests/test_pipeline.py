"""End-to-end pipeline behaviour and the deliverables it produces."""

from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from eu_wholesale import pipeline
from eu_wholesale.reporting.management_report import build_excel_report, group_trend
from eu_wholesale.reporting.powerbi_export import RELATIONSHIPS, export_powerbi


def test_artifacts_round_trip_through_disk(artifacts, small_config):
    reloaded = pipeline.load_artifacts(small_config)
    assert reloaded.champion == artifacts.champion
    assert len(reloaded.forecast) == len(artifacts.forecast)
    assert reloaded.meta["champion_wape"] == pytest.approx(artifacts.meta["champion_wape"])


def test_every_view_reconciles_to_the_same_total(artifacts):
    """Country, product and group views are bottom-up sums of one fact table."""
    mart = artifacts.mart_market
    total = mart["revenue_eur"].sum()
    assert mart.groupby("country_code")["revenue_eur"].sum().sum() == pytest.approx(total)
    assert mart.groupby("product_id")["revenue_eur"].sum().sum() == pytest.approx(total)
    assert artifacts.mart_customer["revenue_eur"].sum() == pytest.approx(total, rel=1e-9)


def test_forecast_aggregates_reconcile(artifacts):
    fc = artifacts.forecast
    total = fc["forecast_eur"].sum()
    assert fc.groupby("country_code")["forecast_eur"].sum().sum() == pytest.approx(total)
    assert fc.groupby("year_month")["forecast_eur"].sum().sum() == pytest.approx(total)


def test_group_trend_joins_history_to_forecast(artifacts):
    trend = group_trend(artifacts)
    assert trend["year_month"].is_monotonic_increasing
    handover = trend[trend["actual_eur_m"].notna() & trend["forecast_eur_m"].notna()]
    assert len(handover) == 1, "history and forecast should meet at exactly one month"
    row = handover.iloc[0]
    assert row["actual_eur_m"] == pytest.approx(row["forecast_eur_m"])


def test_excel_workbook_contains_every_expected_sheet(artifacts):
    path = artifacts.cfg.root / build_excel_report(artifacts, "test_report.xlsx")
    assert path.exists() and path.stat().st_size > 20_000

    import openpyxl
    book = openpyxl.load_workbook(path)
    expected = {"Read me", "KPI Summary", "Market View", "Product View",
                "Customer View", "Trend & Forecast", "Scenarios",
                "Forecast Accuracy", "Revenue Bridge", "Data - Monthly", "Validation"}
    assert expected <= set(book.sheetnames)

    with zipfile.ZipFile(path) as z:
        charts = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
    assert len(charts) >= 8, "workbook should carry native Excel charts"


def test_powerbi_package_is_complete_and_joinable(artifacts):
    written = export_powerbi(artifacts)
    folder = artifacts.cfg.path("powerbi")
    for name in ("dim_date", "dim_country", "dim_product", "dim_customer",
                 "dim_scenario", "fact_revenue", "fact_forecast", "fact_scenario"):
        assert name in written, f"{name} missing from the export"
        assert (folder / f"{name}.csv").exists()
    assert (folder / "measures.dax").exists()
    assert (folder / "model_relationships.csv").exists()

    # Every declared relationship must actually resolve against the exports.
    tables = {p.stem: pd.read_csv(p) for p in folder.glob("*.csv")}
    for from_t, from_c, to_t, to_c, *_ in RELATIONSHIPS:
        assert from_t in tables and to_t in tables, f"{from_t} or {to_t} not exported"
        assert from_c in tables[from_t].columns, f"{from_t}.{from_c} missing"
        assert to_c in tables[to_t].columns, f"{to_t}.{to_c} missing"
        orphans = set(tables[from_t][from_c].dropna()) - set(tables[to_t][to_c].dropna())
        assert not orphans, f"{from_t}.{from_c} has keys absent from {to_t}: {list(orphans)[:3]}"


def test_dimension_keys_are_unique_in_the_export(artifacts):
    folder = artifacts.cfg.path("powerbi")
    export_powerbi(artifacts)
    for table, key in (("dim_date", "year_month"), ("dim_country", "country_code"),
                       ("dim_product", "product_id"), ("dim_customer", "customer_id"),
                       ("dim_scenario", "scenario")):
        frame = pd.read_csv(folder / f"{table}.csv")
        assert frame[key].is_unique, f"{table}.{key} is not unique - relationship would fail"
