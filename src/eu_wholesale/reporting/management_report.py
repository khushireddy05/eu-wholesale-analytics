"""Composition of the Excel management report.

Turns pipeline artifacts into the finished workbook. Each function owns one
sheet, so the report layout is readable top to bottom and a sheet can be
changed without touching the rest.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from .. import kpis
from ..forecasting.scenarios import scenario_monthly, scenario_spread, scenario_summary
from ..pipeline import Artifacts
from .excel_report import ACCENT, ACCENT_LIGHT, NEGATIVE, POSITIVE, ReportWorkbook, sheet_range

M = 1e6


# ---------------------------------------------------------------------------
# Shared data preparation
# ---------------------------------------------------------------------------
def group_trend(art: Artifacts) -> pd.DataFrame:
    """Group revenue by month: actuals, then the forecast with its interval."""
    mart = art.mart_market
    actual = (mart.groupby("year_month", as_index=False)["revenue_eur"].sum()
                  .rename(columns={"revenue_eur": "actual_eur_m"}))
    actual["actual_eur_m"] /= M

    fc = (art.forecast.groupby("year_month", as_index=False)
              .agg(forecast_eur_m=("forecast_eur", "sum"),
                   lower_eur_m=("forecast_lo_eur", "sum"),
                   upper_eur_m=("forecast_hi_eur", "sum")))
    for c in ("forecast_eur_m", "lower_eur_m", "upper_eur_m"):
        fc[c] /= M

    out = actual.merge(fc, on="year_month", how="outer").sort_values("year_month")
    # Join the two lines at the handover month so the chart reads as one path.
    last_actual = out["actual_eur_m"].last_valid_index()
    if last_actual is not None:
        value = out.loc[last_actual, "actual_eur_m"]
        for c in ("forecast_eur_m", "lower_eur_m", "upper_eur_m"):
            out.loc[last_actual, c] = value
    return out.reset_index(drop=True)


def year_matrix(mart: pd.DataFrame, index: str, value: str = "revenue_eur",
                label: str | None = None) -> pd.DataFrame:
    """Dimension x calendar-year matrix in EUR m, with CAGR and share."""
    df = kpis.add_period_columns(mart)
    pivot = (df.pivot_table(index=index, columns="year", values=value,
                            aggfunc="sum", fill_value=0.0) / M)
    pivot.columns = [str(c) for c in pivot.columns]
    full_years = [c for c in pivot.columns
                  if (df[df["year"] == int(c)]["year_month"].nunique() == 12)]
    if len(full_years) >= 2:
        first, last = full_years[0], full_years[-1]
        span = int(last) - int(first)
        pivot["cagr_pct"] = [
            kpis.cagr(row[first], row[last], span) for _, row in pivot.iterrows()
        ]
    latest = pivot.columns[len(full_years) - 1] if full_years else pivot.columns[-1]
    pivot["share_pct"] = pivot[latest] / pivot[latest].sum()
    out = pivot.reset_index()
    if label:
        out = out.rename(columns={index: label})
    return out.sort_values(out.columns[len(full_years)], ascending=False)


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------
def sheet_readme(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Read me", ACCENT)
    ws.set_column(0, 0, 34)
    ws.set_column(1, 1, 96)
    cfg = art.cfg
    meta = art.meta

    row = wb.heading(ws, cfg.project["name"],
                     "Wholesale performance, forecast and scenario pack")
    facts = [
        ("Reporting currency", cfg.currency),
        ("Actuals window", f"{meta['history_start']} to {meta['history_end']} "
                           f"({len(cfg.history_months)} months)"),
        ("Forecast window", f"{cfg.forecast_months[0]} to {cfg.forecast_months[-1]} "
                            f"({cfg.horizon} months)"),
        ("Markets in scope", f"{art.mart_market['country_code'].nunique()} EU markets"),
        ("Product portfolio", f"{art.mart_market['product_id'].nunique()} wholesale products"),
        ("Customer base", f"{art.mart_customer['customer_id'].nunique()} accounts"),
        ("Forecast model", f"{meta['champion_model']} (selected on "
                           f"{meta['selection_metric'].upper()})"),
        ("Backtest accuracy", f"WAPE {meta['champion_wape']:.1f}% versus "
                              f"{meta['benchmark_wape']:.1f}% for the seasonal-naive "
                              f"benchmark ({meta['improvement_vs_benchmark_pct']:.0f}% better)"),
        ("Backtest origins", ", ".join(meta["backtest_origins"])),
        ("Generated", datetime.fromisoformat(meta["generated_at"]).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    row = wb.section(ws, "Pack at a glance", row, width=2)
    for label, value in facts:
        ws.write(row, 0, label, wb.f["kpi_label"])
        ws.write(row, 1, value, wb.f["text"])
        row += 1
    row += 1

    row = wb.section(ws, "How to read this pack", row, width=2)
    guide = [
        ("KPI Summary", "Group headline KPIs, rolling-12-month product and market mix, "
                        "and the actual-versus-forecast revenue path."),
        ("Market View", "Revenue by country and year with growth, share and margin. "
                        "Filter the table or pivot the Data sheet for a country deep-dive."),
        ("Product View", "Portfolio performance by product and lifecycle stage, with "
                         "realised unit price and traffic volume trends."),
        ("Customer View", "Account-level performance, segment mix, concentration and "
                          "net revenue retention."),
        ("Trend & Forecast", "Monthly actuals followed by the 12-month forecast with an "
                             "empirical 80% prediction interval."),
        ("Scenarios", "Baseline, upside and downside paths built by adjusting the price "
                      "and volume drivers of the statistical forecast."),
        ("Forecast Accuracy", "Rolling-origin backtest results: model comparison and "
                              "error by horizon, product and market."),
        ("Revenue Bridge", "Year-on-year revenue movement decomposed into volume, price, "
                           "joint, new and lost business effects."),
        ("Data - Monthly", "Flat, pivot-ready fact table behind every view."),
        ("Validation", "Data contract results. Every figure in this pack comes from data "
                       "that passed these checks."),
    ]
    for name, desc in guide:
        ws.write(row, 0, name, wb.f["text_bold"])
        ws.write(row, 1, desc, wb.f["note"])
        row += 1
    row += 1

    row = wb.section(ws, "Method and definitions", row, width=2)
    notes = [
        ("Forecast approach",
         "Direct multi-horizon regression: a separate model is fitted for each of the "
         "twelve horizons, using only information available at the forecast origin. "
         "Candidates are a seasonal-naive benchmark, ridge and elastic-net regressions "
         "and a gradient-boosted ensemble; the champion is selected on backtest WAPE."),
        ("Forecast grain",
         "Models are fitted at market x product level. Country, product and group "
         "totals are bottom-up sums of the same base forecast, so every view "
         "reconciles."),
        ("Prediction interval",
         "Derived from realised backtest errors by horizon, not from a distributional "
         "assumption. The band widens with horizon because measured error does."),
        ("WAPE",
         "Weighted absolute percentage error: total absolute error divided by total "
         "actual. Preferred over MAPE for revenue because it is not distorted by small "
         "denominators and aggregates across markets of different size."),
        ("Realised unit price",
         "Revenue divided by traffic volume. Aggregated views recompute it from summed "
         "revenue and volume rather than averaging a ratio."),
        ("Revenue bridge",
         "dRevenue = P0 x dVolume (volume effect) + V0 x dPrice (price effect) "
         "+ dVolume x dPrice (joint effect), plus separate new and lost business."),
        ("Data",
         "The dataset is synthetic and generated from documented market assumptions. "
         "It contains no customer or commercial data of any real organisation."),
    ]
    for name, desc in notes:
        ws.write(row, 0, name, wb.f["text_bold"])
        ws.write(row, 1, desc, wb.f["note"])
        ws.set_row(row, 30)
        row += 1


def sheet_kpi_summary(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("KPI Summary", ACCENT)
    mart = art.mart_market
    row = wb.heading(ws, "Group KPI summary",
                     "Rolling 12 months to " + art.meta["history_end"]
                     + ", versus the preceding 12 months")

    head = kpis.headline_kpis(art.mart_customer.assign(
        country_code=art.mart_customer["country_code"],
        product_id=art.mart_customer["product_id"]))
    row = wb.section(ws, "Headline KPIs", row, width=6)
    row = wb.table(ws, head.rename(columns={"kpi": "KPI"}), row,
                   widths={"KPI": 30}, autofilter=False)

    prod = kpis.yoy_table(mart, "product_id")
    prod = prod.merge(art.tables["dim_product"][["product_id", "product_name",
                                                 "lifecycle_stage"]],
                      on="product_id", how="left")
    prod = prod[["product_id", "product_name", "lifecycle_stage", "current_12m",
                 "prior_12m", "delta_abs", "delta_pct", "share_pct"]]
    for c in ("current_12m", "prior_12m", "delta_abs"):
        prod[c] /= M
    prod = prod.rename(columns={"current_12m": "current_12m_eur_m",
                                "prior_12m": "prior_12m_eur_m",
                                "delta_abs": "delta_eur_m"})
    row = wb.section(ws, "Product mix and growth", row, width=8)
    start = row
    row = wb.table(ws, prod, row, total_row=True)
    wb.chart(ws, "column", f"J{start + 1}", "Rolling 12-month revenue by product (EUR m)",
             [{"name": "Current 12m",
               "categories": sheet_range("KPI Summary", start + 1, 1, start + len(prod), 1),
               "values": sheet_range("KPI Summary", start + 1, 3, start + len(prod), 3),
               "color": ACCENT},
              {"name": "Prior 12m",
               "categories": sheet_range("KPI Summary", start + 1, 1, start + len(prod), 1),
               "values": sheet_range("KPI Summary", start + 1, 4, start + len(prod), 4),
               "color": ACCENT_LIGHT}],
             y_title="EUR m", height=300)

    ctry = kpis.yoy_table(mart, "country_code")
    ctry = ctry.merge(art.tables["dim_country"][["country_code", "country_name", "region"]],
                      on="country_code", how="left")
    ctry = ctry[["country_code", "country_name", "region", "current_12m",
                 "prior_12m", "delta_abs", "delta_pct", "share_pct"]]
    for c in ("current_12m", "prior_12m", "delta_abs"):
        ctry[c] /= M
    ctry = ctry.rename(columns={"current_12m": "current_12m_eur_m",
                                "prior_12m": "prior_12m_eur_m",
                                "delta_abs": "delta_eur_m"})
    row = wb.section(ws, "Market mix and growth", row, width=8)
    start = row
    row = wb.table(ws, ctry, row, total_row=True)
    wb.chart(ws, "bar", f"J{start + 1}", "Rolling 12-month revenue by market (EUR m)",
             [{"name": "Current 12m",
               "categories": sheet_range("KPI Summary", start + 1, 1, start + len(ctry), 1),
               "values": sheet_range("KPI Summary", start + 1, 3, start + len(ctry), 3),
               "color": ACCENT}],
             y_title="EUR m", height=380)


def sheet_market_view(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Market View", "#8A5A2B")
    mart = art.mart_market
    row = wb.heading(ws, "Market performance",
                     "Revenue by market and year, with growth, mix and profitability")

    matrix = year_matrix(mart, "country_code")
    matrix = matrix.merge(art.tables["dim_country"][["country_code", "country_name",
                                                     "region", "market_maturity"]],
                          on="country_code", how="left")
    cols = ["country_code", "country_name", "region", "market_maturity"] + \
           [c for c in matrix.columns if c.isdigit()] + ["cagr_pct", "share_pct"]
    row = wb.section(ws, "Revenue by market and year (EUR m)", row, width=len(cols))
    start = row
    row = wb.table(ws, matrix[cols], row, total_row=True)

    year_cols = [c for c in matrix.columns if c.isdigit()]
    first_year_col = 4
    wb.chart(ws, "line", f"B{row + 1}", "Revenue trajectory by market (EUR m)",
             [{"name": sheet_range("Market View", start + i + 1, 1,
                                   start + i + 1, 1),
               "categories": sheet_range("Market View", start, first_year_col,
                                         start, first_year_col + len(year_cols) - 1),
               "values": sheet_range("Market View", start + i + 1, first_year_col,
                                     start + i + 1, first_year_col + len(year_cols) - 1),
               "fill": False}
              for i in range(min(6, len(matrix)))],
             y_title="EUR m", x_title="Year", height=340)
    row += 18

    prof = kpis.aggregate(
        kpis.add_period_columns(mart)[lambda d: d["year_month"] >= _last_12_start(mart)],
        by=["country_code", "product_family"])
    prof = prof.pivot_table(index="country_code", columns="product_family",
                            values="revenue_eur", aggfunc="sum", fill_value=0.0) / M
    prof = prof.reset_index()
    row = wb.section(ws, "Rolling 12-month revenue by market and product family (EUR m)",
                     row, width=len(prof.columns))
    row = wb.table(ws, prof, row, total_row=True)

    margin = kpis.aggregate(mart[mart["year_month"] >= _last_12_start(mart)],
                            by=["country_code"])
    margin = margin.merge(
        kpis.aggregate(mart[(mart["year_month"] >= _prior_12_start(mart))
                            & (mart["year_month"] < _last_12_start(mart))],
                       by=["country_code"]),
        on="country_code", suffixes=("", "_prior"))
    margin["margin_pct_prior"] = margin["margin_eur_prior"] / margin["revenue_eur_prior"]
    margin["margin_delta_pp"] = (margin["margin_pct"] - margin["margin_pct_prior"]) * 100
    margin = margin[["country_code", "revenue_eur", "margin_eur", "margin_pct",
                     "margin_pct_prior", "margin_delta_pp"]]
    margin[["revenue_eur", "margin_eur"]] /= M
    margin = margin.rename(columns={"revenue_eur": "revenue_eur_m",
                                    "margin_eur": "margin_eur_m"})
    row = wb.section(ws, "Gross margin by market", row, width=6)
    wb.table(ws, margin.sort_values("revenue_eur_m", ascending=False), row)


def sheet_product_view(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Product View", "#4C6EF5")
    mart = art.mart_market
    row = wb.heading(ws, "Product portfolio",
                     "Revenue, realised price and traffic volume by wholesale product")

    matrix = year_matrix(mart, "product_id")
    matrix = matrix.merge(art.tables["dim_product"][["product_id", "product_name",
                                                     "product_family", "lifecycle_stage",
                                                     "unit"]],
                          on="product_id", how="left")
    year_cols = [c for c in matrix.columns if c.isdigit()]
    cols = ["product_id", "product_name", "product_family", "lifecycle_stage"] + \
        year_cols + ["cagr_pct", "share_pct"]
    row = wb.section(ws, "Revenue by product and year (EUR m)", row, width=len(cols))
    start = row
    row = wb.table(ws, matrix[cols], row, total_row=True)
    wb.chart(ws, "column", f"B{row + 1}", "Revenue by product and year (EUR m)",
             [{"name": sheet_range("Product View", start + i + 1, 1, start + i + 1, 1),
               "categories": sheet_range("Product View", start, 4, start, 4 + len(year_cols) - 1),
               "values": sheet_range("Product View", start + i + 1, 4,
                                     start + i + 1, 4 + len(year_cols) - 1)}
              for i in range(len(matrix))],
             y_title="EUR m", x_title="Year", subtype="stacked", height=360)
    row += 19

    # Realised price and volume, indexed so products on different units compare.
    idx = kpis.add_period_columns(mart)
    annual = idx.groupby(["product_id", "year"], as_index=False).agg(
        revenue_eur=("revenue_eur", "sum"), volume_units=("volume_units", "sum"))
    annual["unit_price_eur"] = annual["revenue_eur"] / annual["volume_units"]
    base = annual.groupby("product_id")[["unit_price_eur", "volume_units"]].transform("first")
    annual["price_index"] = annual["unit_price_eur"] / base["unit_price_eur"] * 100
    annual["volume_index"] = annual["volume_units"] / base["volume_units"] * 100

    price_p = annual.pivot_table(index="product_id", columns="year",
                                 values="price_index").round(1).reset_index()
    price_p.columns = [str(c) for c in price_p.columns]
    row = wb.section(ws, "Realised unit price, indexed to the first year (100 = base)",
                     row, width=len(price_p.columns))
    p_start = row
    row = wb.table(ws, price_p, row, autofilter=False)
    wb.chart(ws, "line", f"J{p_start + 1}", "Realised unit price index by product",
             [{"name": sheet_range("Product View", p_start + i + 1, 0, p_start + i + 1, 0),
               "categories": sheet_range("Product View", p_start, 1, p_start,
                                         len(price_p.columns) - 1),
               "values": sheet_range("Product View", p_start + i + 1, 1,
                                     p_start + i + 1, len(price_p.columns) - 1),
               "fill": False}
              for i in range(len(price_p))],
             y_title="Index (base year = 100)", height=320)

    vol_p = annual.pivot_table(index="product_id", columns="year",
                               values="volume_index").round(1).reset_index()
    vol_p.columns = [str(c) for c in vol_p.columns]
    row = wb.section(ws, "Traffic volume, indexed to the first year (100 = base)",
                     row, width=len(vol_p.columns))
    v_start = row
    row = wb.table(ws, vol_p, row, autofilter=False)
    wb.chart(ws, "line", f"J{v_start + 1}", "Traffic volume index by product",
             [{"name": sheet_range("Product View", v_start + i + 1, 0, v_start + i + 1, 0),
               "categories": sheet_range("Product View", v_start, 1, v_start,
                                         len(vol_p.columns) - 1),
               "values": sheet_range("Product View", v_start + i + 1, 1,
                                     v_start + i + 1, len(vol_p.columns) - 1),
               "fill": False}
              for i in range(len(vol_p))],
             y_title="Index (base year = 100)", height=320)


def sheet_customer_view(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Customer View", "#7048A8")
    mc = art.mart_customer
    row = wb.heading(ws, "Customer and segment performance",
                     "Rolling 12 months to " + art.meta["history_end"])

    conc = kpis.concentration(mc)
    nrr = kpis.net_revenue_retention(mc)
    churned = int((art.tables["dim_customer"]["status"] == "Churned").sum())
    stats = pd.DataFrame([
        {"metric": "Active accounts (last 12m)", "value": conc["n"]},
        {"metric": "Top-1 customer share", "value": conc["top_1_share"]},
        {"metric": "Top-10 customer share", "value": conc["top_10_share"]},
        {"metric": "Herfindahl-Hirschman index", "value": conc["hhi"]},
        {"metric": "Net revenue retention", "value": nrr},
        {"metric": "Accounts churned in window", "value": churned},
    ])
    row = wb.section(ws, "Portfolio structure", row, width=2)
    for _, rec in stats.iterrows():
        ws.write(row, 0, rec["metric"], wb.f["kpi_label"])
        fmt = wb.f["pct1"] if "share" in rec["metric"].lower() or "retention" in \
            rec["metric"].lower() else wb.f["num1"]
        ws.write_number(row, 1, float(rec["value"]), fmt)
        row += 1
    ws.set_column(0, 0, 32)
    ws.set_column(1, 1, 14)
    row += 1

    seg = kpis.yoy_table(mc, "segment")
    for c in ("current_12m", "prior_12m", "delta_abs"):
        seg[c] /= M
    seg = seg.rename(columns={"current_12m": "current_12m_eur_m",
                              "prior_12m": "prior_12m_eur_m",
                              "delta_abs": "delta_eur_m"})
    row = wb.section(ws, "Revenue by customer segment", row, width=6)
    s_start = row
    row = wb.table(ws, seg, row, total_row=True)
    wb.chart(ws, "column", f"J{s_start + 1}", "Revenue by segment (EUR m)",
             [{"name": "Current 12m",
               "categories": sheet_range("Customer View", s_start + 1, 0, s_start + len(seg), 0),
               "values": sheet_range("Customer View", s_start + 1, 1, s_start + len(seg), 1),
               "color": ACCENT},
              {"name": "Prior 12m",
               "categories": sheet_range("Customer View", s_start + 1, 0, s_start + len(seg), 0),
               "values": sheet_range("Customer View", s_start + 1, 2, s_start + len(seg), 2),
               "color": ACCENT_LIGHT}],
             y_title="EUR m", height=300)

    top = kpis.yoy_table(mc, "customer_id").head(25)
    top = top.merge(art.tables["dim_customer"][["customer_id", "customer_name",
                                                "country_code", "segment",
                                                "customer_tier", "contract_type",
                                                "status"]],
                    on="customer_id", how="left")
    for c in ("current_12m", "prior_12m", "delta_abs"):
        top[c] /= M
    top = top.rename(columns={"current_12m": "current_12m_eur_m",
                              "prior_12m": "prior_12m_eur_m",
                              "delta_abs": "delta_eur_m"})
    top = top[["customer_id", "customer_name", "country_code", "segment",
               "customer_tier", "contract_type", "status", "current_12m_eur_m",
               "prior_12m_eur_m", "delta_eur_m", "delta_pct", "share_pct"]]
    row = wb.section(ws, "Top 25 accounts by rolling 12-month revenue", row, width=12)
    start = row
    row = wb.table(ws, top, row)
    ws.conditional_format(start + 1, 10, start + len(top), 10,
                          {"type": "3_color_scale",
                           "min_color": NEGATIVE, "mid_color": "#FFFFFF",
                           "max_color": POSITIVE})

    movers = kpis.yoy_table(mc, "customer_id")
    movers = movers.merge(art.tables["dim_customer"][["customer_id", "customer_name",
                                                      "country_code", "segment"]],
                          on="customer_id", how="left")
    movers["delta_abs"] /= M
    movers = movers.rename(columns={"delta_abs": "delta_eur_m"})
    biggest = pd.concat([movers.nlargest(10, "delta_eur_m"),
                         movers.nsmallest(10, "delta_eur_m")])
    biggest = biggest[["customer_id", "customer_name", "country_code", "segment",
                       "delta_eur_m", "delta_pct"]]
    row = wb.section(ws, "Largest year-on-year movers (top 10 up, top 10 down)",
                     row, width=6)
    wb.table(ws, biggest, row)


def sheet_trend_forecast(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Trend & Forecast", "#1F7A4D")
    row = wb.heading(ws, "Revenue trend and forecast",
                     f"Actuals to {art.meta['history_end']}, then a {art.cfg.horizon}-month "
                     f"{art.meta['champion_model']} forecast with an 80% prediction interval")

    trend = group_trend(art)
    row = wb.section(ws, "Group monthly revenue (EUR m)", row, width=5)
    start = row
    nxt = wb.table(ws, trend, row, autofilter=False)
    n = len(trend)
    wb.chart(ws, "line", f"H{start + 1}",
             "Group revenue: actual and forecast (EUR m)",
             [{"name": "Actual",
               "categories": sheet_range("Trend & Forecast", start + 1, 0, start + n, 0),
               "values": sheet_range("Trend & Forecast", start + 1, 1, start + n, 1),
               "color": ACCENT, "fill": False},
              {"name": "Forecast",
               "categories": sheet_range("Trend & Forecast", start + 1, 0, start + n, 0),
               "values": sheet_range("Trend & Forecast", start + 1, 2, start + n, 2),
               "color": NEGATIVE, "fill": False, "dash": "dash"},
              {"name": "Lower bound",
               "categories": sheet_range("Trend & Forecast", start + 1, 0, start + n, 0),
               "values": sheet_range("Trend & Forecast", start + 1, 3, start + n, 3),
               "color": "#C9CFD6", "fill": False, "dash": "round_dot"},
              {"name": "Upper bound",
               "categories": sheet_range("Trend & Forecast", start + 1, 0, start + n, 0),
               "values": sheet_range("Trend & Forecast", start + 1, 4, start + n, 4),
               "color": "#C9CFD6", "fill": False, "dash": "round_dot"}],
             y_title="EUR m", width=900, height=420)
    row = nxt + 20

    fc = art.forecast
    by_product = (fc.groupby("product_id", as_index=False)
                    .agg(forecast_eur=("forecast_eur", "sum"),
                         lower_eur=("forecast_lo_eur", "sum"),
                         upper_eur=("forecast_hi_eur", "sum")))
    last12 = art.mart_market[art.mart_market["year_month"] >= _last_12_start(art.mart_market)]
    actual_p = last12.groupby("product_id", as_index=False)["revenue_eur"].sum()
    by_product = by_product.merge(actual_p, on="product_id", how="left")
    by_product = by_product.merge(
        art.tables["dim_product"][["product_id", "product_name", "lifecycle_stage"]],
        on="product_id", how="left")
    by_product["growth_pct"] = by_product["forecast_eur"] / by_product["revenue_eur"] - 1
    for c in ("forecast_eur", "lower_eur", "upper_eur", "revenue_eur"):
        by_product[c] /= M
    by_product = by_product.rename(columns={
        "revenue_eur": "last_12m_eur_m", "forecast_eur": "next_12m_eur_m",
        "lower_eur": "lower_eur_m", "upper_eur": "upper_eur_m"})
    by_product = by_product[["product_id", "product_name", "lifecycle_stage",
                             "last_12m_eur_m", "next_12m_eur_m", "lower_eur_m",
                             "upper_eur_m", "growth_pct"]]
    row = wb.section(ws, "Next 12 months by product", row, width=8)
    row = wb.table(ws, by_product.sort_values("next_12m_eur_m", ascending=False),
                   row, total_row=True)

    by_country = (fc.groupby("country_code", as_index=False)["forecast_eur"].sum()
                    .merge(last12.groupby("country_code", as_index=False)["revenue_eur"].sum(),
                           on="country_code", how="left"))
    by_country["growth_pct"] = by_country["forecast_eur"] / by_country["revenue_eur"] - 1
    by_country[["forecast_eur", "revenue_eur"]] /= M
    by_country = by_country.rename(columns={"revenue_eur": "last_12m_eur_m",
                                            "forecast_eur": "next_12m_eur_m"})
    row = wb.section(ws, "Next 12 months by market", row, width=4)
    wb.table(ws, by_country.sort_values("next_12m_eur_m", ascending=False),
             row, total_row=True)


def sheet_scenarios(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Scenarios", "#B58900")
    cfg = art.cfg
    row = wb.heading(ws, "Scenario analysis",
                     "Driver-based adjustments to the statistical forecast")

    assumptions = pd.DataFrame([
        {"scenario": spec.get("label", key.title()),
         "price_effect_pa": float(spec.get("price_effect_pa", 0.0)),
         "volume_effect_pa": float(spec.get("volume_effect_pa", 0.0)),
         "description": spec.get("description", "")}
        for key, spec in cfg.scenarios.items()
    ])
    row = wb.section(ws, "Assumptions", row, width=4)
    row = wb.table(ws, assumptions, row, widths={"description": 78}, autofilter=False)

    summary = scenario_summary(art.scenarios, art.mart_market)
    summary_disp = summary.copy()
    for c in ("next_12m_eur", "last_12m_eur", "delta_eur"):
        summary_disp[c] /= M
    summary_disp = summary_disp.rename(columns={
        "next_12m_eur": "next_12m_eur_m", "last_12m_eur": "last_12m_eur_m",
        "delta_eur": "delta_eur_m"})
    row = wb.section(ws, "Group outcome by scenario", row, width=5)
    row = wb.table(ws, summary_disp, row, autofilter=False)

    spread = scenario_spread(summary)
    ws.write(row, 0, "Planning range (upside less downside)", wb.f["kpi_label"])
    ws.write_number(row, 1, spread["spread_eur"] / M, wb.f["eur1"])
    ws.write(row, 2, "EUR m", wb.f["kpi_label"])
    ws.write_number(row, 3, spread["spread_pct_of_baseline"], wb.f["pct1"])
    ws.write(row, 4, "of baseline", wb.f["kpi_label"])
    row += 3

    monthly = scenario_monthly(art.scenarios)
    wide = monthly.pivot_table(index="year_month", columns="scenario",
                               values="forecast_eur", observed=True) / M
    wide = wide.reset_index()
    wide.columns = [str(c) for c in wide.columns]
    row = wb.section(ws, "Monthly path by scenario (EUR m)", row, width=4)
    start = row
    nxt = wb.table(ws, wide, row, autofilter=False)
    n = len(wide)
    wb.chart(ws, "line", f"G{start + 1}", "Forecast path by scenario (EUR m)",
             [{"name": sheet_range("Scenarios", start, i, start, i),
               "categories": sheet_range("Scenarios", start + 1, 0, start + n, 0),
               "values": sheet_range("Scenarios", start + 1, i, start + n, i),
               "fill": False}
              for i in range(1, len(wide.columns))],
             y_title="EUR m", height=340)
    row = nxt + 18

    by_prod = scenario_summary(art.scenarios, art.mart_market, by=["product_id"])
    for c in ("next_12m_eur", "last_12m_eur", "delta_eur"):
        by_prod[c] /= M
    by_prod = by_prod.rename(columns={"next_12m_eur": "next_12m_eur_m",
                                      "last_12m_eur": "last_12m_eur_m",
                                      "delta_eur": "delta_eur_m"})
    row = wb.section(ws, "Scenario outcome by product", row, width=6)
    wb.table(ws, by_prod, row)


def sheet_accuracy(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Forecast Accuracy", "#B4232C")
    meta = art.meta
    row = wb.heading(
        ws, "Forecast accuracy",
        f"Rolling-origin backtest over {len(meta['backtest_origins'])} forecast origins: "
        + ", ".join(meta["backtest_origins"]))

    models = art.accuracy["accuracy_by_model"].copy()
    models["vs_benchmark_pct"] = (
        (meta["benchmark_wape"] - models["wape"]) / meta["benchmark_wape"])
    models["selected"] = np.where(models["model"] == meta["champion_model"],
                                  "Champion", "")
    models = models[["model", "selected", "mae", "rmse", "mape", "smape", "wape",
                     "bias_pct", "vs_benchmark_pct", "n_obs"]]
    row = wb.section(ws, "Model comparison", row, width=10)
    start = row
    row = wb.table(ws, models, row, autofilter=False)
    wb.chart(ws, "column", f"L{start + 1}", "WAPE by model (%, lower is better)",
             [{"name": "WAPE %",
               "categories": sheet_range("Forecast Accuracy", start + 1, 0,
                                         start + len(models), 0),
               "values": sheet_range("Forecast Accuracy", start + 1, 6,
                                     start + len(models), 6),
               "color": ACCENT}],
             y_title="WAPE %", height=300)

    hor = art.accuracy["accuracy_by_horizon"].sort_values("horizon")
    hor = hor[["horizon", "mae", "mape", "smape", "wape", "bias_pct", "n_obs"]]
    row = wb.section(ws, "Champion accuracy by forecast horizon", row, width=7)
    h_start = row
    row = wb.table(ws, hor, row, autofilter=False)
    wb.chart(ws, "line", f"L{h_start + 1}", "Error by horizon (months ahead)",
             [{"name": "WAPE %",
               "categories": sheet_range("Forecast Accuracy", h_start + 1, 0,
                                         h_start + len(hor), 0),
               "values": sheet_range("Forecast Accuracy", h_start + 1, 4,
                                     h_start + len(hor), 4),
               "color": ACCENT, "fill": False},
              {"name": "Bias %",
               "categories": sheet_range("Forecast Accuracy", h_start + 1, 0,
                                         h_start + len(hor), 0),
               "values": sheet_range("Forecast Accuracy", h_start + 1, 5,
                                     h_start + len(hor), 5),
               "color": NEGATIVE, "fill": False}],
             x_title="Months ahead", y_title="%", height=300)

    prod = art.accuracy["accuracy_by_product"].merge(
        art.tables["dim_product"][["product_id", "product_name"]],
        on="product_id", how="left")
    prod["actual_eur_m"] = prod["actual_eur"] / M
    prod = prod[["product_id", "product_name", "wape", "mape", "bias_pct",
                 "actual_eur_m", "n_obs"]]
    row = wb.section(ws, "Champion accuracy by product", row, width=7)
    row = wb.table(ws, prod, row)

    ctry = art.accuracy["accuracy_by_country"].copy()
    ctry["actual_eur_m"] = ctry["actual_eur"] / M
    ctry = ctry[["country_code", "wape", "mape", "bias_pct", "actual_eur_m", "n_obs"]]
    row = wb.section(ws, "Champion accuracy by market", row, width=6)
    wb.table(ws, ctry, row)


def sheet_bridge(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Revenue Bridge", "#0B7285")
    mart = art.mart_market
    row = wb.heading(ws, "Revenue bridge",
                     "Year-on-year movement decomposed into volume, price and mix effects")

    for dim, label in (("product_id", "product"), ("country_code", "market")):
        bridge = kpis.price_volume_bridge(mart, [dim])
        value_cols = ["revenue_prior", "revenue_current", "revenue_delta",
                      "volume_effect", "price_effect", "joint_effect",
                      "new_business", "lost_business", "unexplained"]
        bridge[value_cols] /= M
        bridge = bridge.rename(columns={c: c + "_eur_m" for c in value_cols})
        bridge = bridge.sort_values("revenue_delta_eur_m", ascending=False)
        row = wb.section(ws, f"Revenue bridge by {label} (EUR m, last 12m vs prior 12m)",
                         row, width=len(bridge.columns))
        start = row
        row = wb.table(ws, bridge, row, total_row=True)
        wb.chart(ws, "column", f"M{start + 1}",
                 f"Volume and price effects by {label} (EUR m)",
                 [{"name": "Volume effect",
                   "categories": sheet_range("Revenue Bridge", start + 1, 0,
                                             start + len(bridge), 0),
                   "values": sheet_range("Revenue Bridge", start + 1, 4,
                                         start + len(bridge), 4),
                   "color": POSITIVE},
                  {"name": "Price effect",
                   "categories": sheet_range("Revenue Bridge", start + 1, 0,
                                             start + len(bridge), 0),
                   "values": sheet_range("Revenue Bridge", start + 1, 5,
                                         start + len(bridge), 5),
                   "color": NEGATIVE}],
                 y_title="EUR m", subtype="stacked", height=320)
        row += 4


def sheet_data(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Data - Monthly", "#6B7684")
    row = wb.heading(ws, "Monthly fact table",
                     "Pivot-ready: one row per month, market and product")
    cols = ["year_month", "year", "quarter", "country_code", "country_name", "region",
            "product_id", "product_name", "product_family", "lifecycle_stage",
            "volume_units", "unit", "unit_price_eur", "revenue_eur", "cost_eur",
            "margin_eur", "margin_pct", "active_customers"]
    data = art.mart_market[cols].copy()
    wb.table(ws, data, row)


def sheet_validation(wb: ReportWorkbook, art: Artifacts) -> None:
    ws = wb.sheet("Validation", "#6B7684")
    row = wb.heading(ws, "Data validation",
                     "Contracts asserted on the raw layer before any analysis ran")
    report = art.tables.get("validation_report")
    if report is None:
        from ..model.validate import validate_tables
        report = validate_tables(art.tables)
    start = row
    row = wb.table(ws, report, row, widths={"detail": 52}, autofilter=False)
    ws.conditional_format(start + 1, 2, start + len(report), 2,
                          {"type": "text", "criteria": "containing", "value": "PASS",
                           "format": wb.f["pass"]})
    ws.conditional_format(start + 1, 2, start + len(report), 2,
                          {"type": "text", "criteria": "containing", "value": "FAIL",
                           "format": wb.f["fail"]})
    ws.write(row, 0, f"{int((report['status'] == 'PASS').sum())} of {len(report)} "
                     f"checks passed.", wb.f["text_bold"])


def sheet_insights(wb: ReportWorkbook, art: Artifacts) -> None:
    """Market commentary from the AI analysis stage, if it has been run."""
    path = art.cfg.path("insights") / "market_commentary.md"
    if not path.exists():
        return

    ws = wb.sheet("Commentary", "#7048A8")
    ws.set_column(0, 0, 118)
    row = wb.heading(ws, "Market commentary",
                     "Written from the validated evidence pack; every figure is cited "
                     "back to a deterministic calculation")

    body = wb.book.add_format({"font_name": "Calibri", "font_size": 10,
                               "text_wrap": True, "valign": "top"})
    h2 = wb.f["h2"]
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            row += 1
            continue
        if text.startswith("## "):
            ws.write(row, 0, text[3:], h2)
            row += 1
        elif text.startswith("# ") or text.startswith("---"):
            continue
        else:
            ws.write(row, 0, text.lstrip("*> ").rstrip("*"), body)
            # Roughly one wrapped line per 115 characters at this column width.
            ws.set_row(row, 13 * max(1, len(text) // 115 + 1))
            row += 1

    verification = art.cfg.path("insights") / "verification_report.csv"
    if verification.exists():
        report = pd.read_csv(verification)
        row = wb.section(ws, "Figure verification", row + 1, width=3)
        ws.write(row, 0, f"{len(report)} figures in the commentary were checked against "
                         f"the evidence pack; "
                         f"{int((report['status'] == 'UNSUPPORTED').sum())} could not be "
                         f"traced to a calculated fact.", wb.f["note"])


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------
def _last_12_start(mart: pd.DataFrame) -> str:
    return sorted(mart["year_month"].unique())[-12]


def _prior_12_start(mart: pd.DataFrame) -> str:
    return sorted(mart["year_month"].unique())[-24]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_excel_report(art: Artifacts, filename: str = "eu_wholesale_management_report.xlsx"
                       ) -> str:
    path = art.cfg.file("excel", filename)
    wb = ReportWorkbook(str(path), art.cfg.project["name"])
    for builder in (sheet_readme, sheet_kpi_summary, sheet_market_view,
                    sheet_product_view, sheet_customer_view, sheet_trend_forecast,
                    sheet_scenarios, sheet_accuracy, sheet_bridge, sheet_insights,
                    sheet_data, sheet_validation):
        builder(wb, art)
    wb.close()
    return str(path.relative_to(art.cfg.root))
