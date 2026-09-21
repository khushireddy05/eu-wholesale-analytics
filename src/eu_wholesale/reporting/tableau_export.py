"""Tableau hand-off package.

Same star schema as the Power BI export, packaged for Tableau Public Desktop:
plain CSVs, a calculated-field library in Tableau's formula syntax (instead of
DAX), a relationships guide, a precomputed KPI snapshot for the metrics that
are awkward to express as Tableau LOD expressions, and a build guide aimed
specifically at Tableau Public's free workflow (no paid license, no server).

Design choice: rather than re-deriving net revenue retention, customer HHI and
concentration inside Tableau's calculation language - which needs nested LOD
expressions most Tableau Public users will not want to hand-write - those
metrics are computed once here, the same way the rest of the project computes
every number, and shipped as a flat monthly table. Tableau's job stays what
it is good at: encoding and letting the reader interact, not deriving.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from .. import kpis
from ..config import Config
from ..pipeline import Artifacts

RELATIONSHIPS = [
    # from_table, from_column, to_table, to_column
    ("fact_revenue", "year_month", "dim_date", "year_month"),
    ("fact_revenue", "country_code", "dim_country", "country_code"),
    ("fact_revenue", "product_id", "dim_product", "product_id"),
    ("fact_revenue", "customer_id", "dim_customer", "customer_id"),
    ("fact_forecast", "year_month", "dim_date", "year_month"),
    ("fact_forecast", "country_code", "dim_country", "country_code"),
    ("fact_forecast", "product_id", "dim_product", "product_id"),
    ("fact_scenario", "year_month", "dim_date", "year_month"),
    ("fact_scenario", "country_code", "dim_country", "country_code"),
    ("fact_scenario", "product_id", "dim_product", "product_id"),
    ("fact_scenario", "scenario", "dim_scenario", "scenario"),
    ("fact_market_indicator", "year_month", "dim_date", "year_month"),
    ("fact_market_indicator", "country_code", "dim_country", "country_code"),
    ("fact_backtest", "target_year_month", "dim_date", "year_month"),
    ("fact_backtest", "country_code", "dim_country", "country_code"),
    ("fact_backtest", "product_id", "dim_product", "product_id"),
    ("fact_kpi_snapshot", "year_month", "dim_date", "year_month"),
]

BUILD_GUIDE = """# Tableau Public — build guide

Free workflow, no license required. Everything below uses **Tableau Public
Desktop** (download at tableau.com/products/public), which is a full Tableau
Desktop app that can only save/publish to Tableau's public cloud.

**Before you start:** anything you publish with "Save to Tableau Public" is
public — visible to anyone with the link and potentially indexed in Tableau's
public gallery. There is no private-workbook option on the free tier. Publish
with that in mind.

## 1. Connect the data

1. Open Tableau Public Desktop > **Connect > To a File > Text file** (or
   **Folder**, to bring in every CSV in this directory at once).
2. Point it at this folder. Each CSV becomes a table on the canvas in the
   **Data Source** tab.

## 2. Build the relationships (not joins)

Drag each fact table onto the canvas, then drag a dimension table near it —
Tableau shows a relationship line automatically when column names hint at a
match, or click the line to set it manually. Use `model_relationships.csv` in
this folder as the exact list: every row is `from_table.from_column ->
to_table.to_column`.

Use **relationships**, not the older physical **joins** — relationships keep
each fact table at its own grain (revenue, forecast and scenario rows don't
multiply against each other) and let Tableau pick the right join type
per-worksheet automatically. This is the modern Tableau default when you drag
tables onto the canvas rather than the "New Union"/"Add Join Clause" toolbar.

## 3. Fix data types

In the Data Source tab, check the type badge under each column header:
- `year_month`, every `*_code` / `*_id` column, `scenario` → **String**
- `date` (in `dim_date`) → **Date**
- every `*_eur`, `*_units`, `*_pct` and index column → **Number (decimal)**

## 4. One continuous actual + forecast line

Tableau doesn't have a native "coalesce across tables" like a DAX/Power BI
measure. The clean way to get one line through history and into the forecast:

- Build the calculated field `Revenue and Forecast` (see
  `calculated_fields.md`, section 04) on a **blended** view of
  `fact_revenue` and `fact_forecast`, **or**
- Simpler: use `fact_revenue` for the solid actuals line and `fact_forecast`
  for a second, dashed line on the same axis (dual-axis chart, synchronized).
  This is what the sample dashboard layout below assumes — it also makes the
  actual/forecast distinction visually obvious, which a single merged line
  loses.

## 5. Add the calculated fields

Open `calculated_fields.md` and create each one via **Analysis > Create
Calculated Field**, copying the formula exactly. They're grouped the same way
as the Power BI DAX file (Core, Time intelligence, Mix and concentration,
Forecast, Scenarios, Accuracy, Formatting). A handful of metrics (NRR, HHI,
concentration) are pre-computed in `fact_kpi_snapshot.csv` instead of being
rebuilt as Tableau LOD expressions — see the note at the end of that file.

## 6. Suggested dashboard layout

One dashboard, four sheets, matching the Excel/Power BI pack:

**Sheet 1 — Trend**: dual-axis line, `fact_revenue.Revenue` (solid) and
`fact_forecast.Forecast Revenue` (dashed) by month, with `Forecast Lower` /
`Forecast Upper` as a shaded reference band (dual-axis area chart).

**Sheet 2 — Market and product mix**: bar chart of `Revenue (EUR m)` by
Country Name and by Product Name, `Revenue YoY %` on colour.

**Sheet 3 — Scenario comparison**: line chart of `Scenario Revenue` by month,
coloured by `Scenario` (from `dim_scenario`), with a scenario filter/legend
toggle.

**Sheet 4 — Accuracy**: bar chart of `WAPE %` by `Model` (from
`fact_backtest`), plus a line of `WAPE %` by `Horizon`.

Assemble all four onto one **Dashboard**, add a Country and Product filter
(applied to all sheets via **Use as Filter**), and a couple of KPI number
cards for `Revenue (EUR m)`, `Revenue YoY %` and `Gross Margin %` at the top.

## 7. Publish

**File > Save to Tableau Public As...**, sign in (free account), name it,
publish. You'll get a shareable link and an embed code.

## 8. Refresh

Re-run the Python pipeline (`python -m eu_wholesale.cli all` then
`python -m eu_wholesale.cli tableau`) to regenerate every CSV, then in
Tableau Public Desktop: **Data > Refresh** picks up the new files as long as
you re-point the connection at the same folder path — column names and types
are stable across runs.
"""


def build_kpi_snapshot(art: Artifacts) -> pd.DataFrame:
    """Trailing-12-month NRR, concentration and HHI, one row per month.

    Precomputed here rather than left to Tableau's calculation language - see
    the module docstring. Each row uses the 12 months ending at that
    ``year_month`` as its trailing window, so the series can be plotted
    directly without any further windowing in Tableau.
    """
    mc = art.mart_customer
    months = sorted(mc["year_month"].unique())
    rows = []
    for i, ym in enumerate(months):
        if i < 11:
            continue
        window = months[i - 11:i + 1]
        sub = mc[mc["year_month"].isin(window)]
        conc = kpis.concentration(sub, months=12)
        # NRR compares the trailing 12 months against the 12 before that, so
        # it needs a 24-month window - a plain 12-month slice would always
        # find nothing in the "prior" half and silently return NaN.
        if i >= 23:
            nrr_window = months[i - 23:i + 1]
            nrr = kpis.net_revenue_retention(mc[mc["year_month"].isin(nrr_window)],
                                             months=12)
        else:
            nrr = float("nan")
        rows.append({
            "year_month": ym,
            "top_1_share": conc["top_1_share"],
            "top_10_share": conc["top_10_share"],
            "hhi": conc["hhi"],
            "active_customers": conc["n"],
            "net_revenue_retention": nrr,
        })
    return pd.DataFrame(rows)


def export_tableau(art: Artifacts) -> dict[str, str]:
    """Write the full Tableau Public hand-off package."""
    cfg: Config = art.cfg
    out = cfg.path("outputs") / "tableau"
    out.mkdir(parents=True, exist_ok=True)

    scenario_labels = art.scenarios["scenario"].astype(str)
    dim_scenario = (art.scenarios.assign(scenario=scenario_labels)
                    [["scenario", "scenario_key", "scenario_description"]]
                    .drop_duplicates()
                    .reset_index(drop=True))
    dim_scenario["sort_order"] = dim_scenario["scenario"].map(
        {"Downside": 1, "Baseline": 2, "Upside": 3}).fillna(9).astype(int)

    backtest = art.accuracy["backtest_predictions"].copy()
    backtest["error"] = backtest["y_pred"] - backtest["y"]
    backtest["abs_error"] = backtest["error"].abs()

    tables: dict[str, pd.DataFrame] = {
        "dim_date": art.tables["dim_date"],
        "dim_country": art.tables["dim_country"],
        "dim_product": art.tables["dim_product"],
        "dim_customer": art.tables["dim_customer"].drop(columns=["products"],
                                                        errors="ignore"),
        "dim_scenario": dim_scenario,
        "fact_revenue": art.tables["fact_traffic"],
        "fact_market_indicator": art.tables["fact_market_indicator"],
        "fact_forecast": art.forecast,
        "fact_scenario": art.scenarios.assign(scenario=scenario_labels)
                            .drop(columns=["scenario_description"], errors="ignore"),
        "fact_backtest": backtest,
        "fact_kpi_snapshot": build_kpi_snapshot(art),
    }

    written: dict[str, str] = {}
    for name, frame in tables.items():
        path = out / f"{name}.csv"
        frame.to_csv(path, index=False)
        written[name] = str(path.relative_to(cfg.root))

    rel = pd.DataFrame(RELATIONSHIPS, columns=["from_table", "from_column",
                                               "to_table", "to_column"])
    rel.to_csv(out / "model_relationships.csv", index=False)
    written["model_relationships"] = str((out / "model_relationships.csv")
                                         .relative_to(cfg.root))

    (out / "README.md").write_text(BUILD_GUIDE, encoding="utf-8")
    written["build_guide"] = str((out / "README.md").relative_to(cfg.root))

    from .. import __file__ as pkg_init
    package_root = Path(pkg_init).resolve().parents[2]
    source_calc = package_root / "tableau" / "calculated_fields.md"
    if source_calc.exists():
        shutil.copy(source_calc, out / "calculated_fields.md")
        written["calculated_fields"] = str((out / "calculated_fields.md")
                                           .relative_to(cfg.root))

    return written
