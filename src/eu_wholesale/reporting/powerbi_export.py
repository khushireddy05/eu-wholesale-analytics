"""Power BI hand-off package.

Writes a clean star schema plus the model metadata a BI developer needs to
stand the report up: the relationship specification, the DAX measure library
and a build guide. Everything lands in one folder that can be pointed at with
Get Data > Folder.

Design decisions that matter for the Power BI model:

* Facts stay at their natural grain and share conformed dimensions, so a single
  date, market or product slicer filters actuals, forecast and scenarios
  together.
* Text keys (``year_month``, ``country_code``, ``product_id``) are used
  throughout - they survive a CSV round-trip without type drift.
* ``dim_date`` carries a real date column so it can be marked as the model's
  date table, which is what makes the time-intelligence measures work.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from ..config import Config
from ..pipeline import Artifacts

RELATIONSHIPS = [
    # from_table, from_column, to_table, to_column, cardinality, direction, active
    ("fact_revenue", "year_month", "dim_date", "year_month", "Many to one", "Single", "Yes"),
    ("fact_revenue", "country_code", "dim_country", "country_code", "Many to one", "Single", "Yes"),
    ("fact_revenue", "product_id", "dim_product", "product_id", "Many to one", "Single", "Yes"),
    ("fact_revenue", "customer_id", "dim_customer", "customer_id", "Many to one", "Single", "Yes"),
    ("fact_forecast", "year_month", "dim_date", "year_month", "Many to one", "Single", "Yes"),
    ("fact_forecast", "country_code", "dim_country", "country_code", "Many to one", "Single", "Yes"),
    ("fact_forecast", "product_id", "dim_product", "product_id", "Many to one", "Single", "Yes"),
    ("fact_scenario", "year_month", "dim_date", "year_month", "Many to one", "Single", "Yes"),
    ("fact_scenario", "country_code", "dim_country", "country_code", "Many to one", "Single", "Yes"),
    ("fact_scenario", "product_id", "dim_product", "product_id", "Many to one", "Single", "Yes"),
    ("fact_scenario", "scenario", "dim_scenario", "scenario", "Many to one", "Single", "Yes"),
    ("fact_market_indicator", "year_month", "dim_date", "year_month", "Many to one", "Single", "Yes"),
    ("fact_market_indicator", "country_code", "dim_country", "country_code", "Many to one", "Single", "Yes"),
    ("fact_backtest", "target_year_month", "dim_date", "year_month", "Many to one", "Single", "Yes"),
    ("fact_backtest", "country_code", "dim_country", "country_code", "Many to one", "Single", "Yes"),
    ("fact_backtest", "product_id", "dim_product", "product_id", "Many to one", "Single", "Yes"),
]

BUILD_GUIDE = """# Power BI model - build guide

This folder is a complete hand-off package. It contains the star-schema data,
the relationship specification, and the DAX measure library.

## 1. Load the data

1. Power BI Desktop > **Home > Get data > Folder** and point at this folder.
2. **Combine > Combine & Transform**, then load every CSV as its own table.
   Keep the file names as table names.
3. In Power Query, confirm the types:
   - `year_month` and all `*_code` / `*_id` columns: **Text**
   - `date`: **Date**
   - all `*_eur`, `*_units`, `*_pct`, index and rate columns: **Decimal number**

## 2. Build the model

1. Create the relationships listed in `model_relationships.csv`. All are
   many-to-one, single direction.
2. Select `dim_date` > **Table tools > Mark as date table** > `date`.
   Time-intelligence measures will not work until this is done.
3. Hide the key columns on the fact tables (`year_month`, `country_code`,
   `product_id`, `customer_id`) so report authors filter through the
   dimensions instead.

## 3. Add the measures

Open `measures.dax` and create each measure (Home > New measure), or import
the file with Tabular Editor. Assign the display folders indicated in the
comments. Set formats:

| Measure group | Format |
|---|---|
| Revenue, Cost, Gross Margin, Forecast | Whole number, thousands separator |
| `* (EUR m)` | Decimal, 1 place |
| `* %` measures | Percentage, 1 place |
| Realised Unit Price | Decimal, 5 places |

## 4. Suggested report pages

**Executive overview** - KPI cards (Revenue R12M, Revenue R12M Growth %,
Gross Margin %, Forecast vs Last 12 Months %), a combined actual-and-forecast
line using `Revenue and Forecast`, revenue by market on a map or bar chart,
and product mix as a stacked column by year.

**Market deep-dive** - country slicer, revenue trend with `Revenue YoY %`,
market share treemap, gross margin by market, and the market indicator panel
(`data_traffic_index`, `travel_index`, `ott_substitution_index`) so the
commercial trend can be read against its driver.

**Product and price** - product slicer, revenue and traffic volume dual-axis
chart, `Realised Unit Price` trend, and a decomposition tree on Revenue split
by market then customer segment.

**Customer** - top-N customer table with `Revenue R12M` and `Revenue YoY %`,
`Top 10 Customer Share %` and `Customer HHI` cards, `Net Revenue Retention %`,
and a segment breakdown.

**Forecast and scenarios** - the actual/forecast line with `Forecast Lower`
and `Forecast Upper` as a shaded band, a scenario slicer driving
`Scenario Revenue`, `Scenario vs Baseline %` by product, and the accuracy page
built on `fact_backtest` (`WAPE %` by model and by horizon, and
`Accuracy Gain vs Benchmark %`).

## 5. Refresh

Re-run the Python pipeline (`python -m eu_wholesale.cli all`) to regenerate
every CSV in place, then refresh in Power BI. Schemas are stable across runs,
so the model and all visuals survive a refresh.
"""


def _table_dictionary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """A data dictionary describing every exported column."""
    rows = []
    for name, frame in tables.items():
        for col in frame.columns:
            series = frame[col]
            rows.append({
                "table": name,
                "column": col,
                "dtype": str(series.dtype),
                "role": ("key" if col.endswith(("_id", "_code")) or col == "year_month"
                         else "measure" if pd.api.types.is_numeric_dtype(series)
                         else "attribute"),
                "non_null": int(series.notna().sum()),
                "distinct": int(series.nunique(dropna=True)),
                "example": "" if series.empty else str(series.dropna().iloc[0])[:40],
            })
    return pd.DataFrame(rows)


def export_powerbi(art: Artifacts) -> dict[str, str]:
    """Write the full Power BI hand-off package."""
    cfg: Config = art.cfg
    out = cfg.path("powerbi")

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
        "fact_accuracy_by_model": art.accuracy["accuracy_by_model"],
        "fact_accuracy_by_horizon": art.accuracy["accuracy_by_horizon"],
    }

    written: dict[str, str] = {}
    for name, frame in tables.items():
        path = out / f"{name}.csv"
        frame.to_csv(path, index=False)
        written[name] = str(path.relative_to(cfg.root))

    rel = pd.DataFrame(RELATIONSHIPS, columns=[
        "from_table", "from_column", "to_table", "to_column",
        "cardinality", "cross_filter_direction", "active"])
    rel.to_csv(out / "model_relationships.csv", index=False)
    written["model_relationships"] = str((out / "model_relationships.csv")
                                         .relative_to(cfg.root))

    _table_dictionary(tables).to_csv(out / "data_dictionary.csv", index=False)
    written["data_dictionary"] = str((out / "data_dictionary.csv").relative_to(cfg.root))

    (out / "README.md").write_text(BUILD_GUIDE, encoding="utf-8")
    written["build_guide"] = str((out / "README.md").relative_to(cfg.root))

    # The DAX library ships alongside the package source, not under the
    # (possibly test-scoped) config root, so it resolves the same way in every
    # environment that has the package installed.
    from .. import config as _config_mod
    package_root = Path(_config_mod.__file__).resolve().parents[2]
    source_dax = package_root / "powerbi" / "measures.dax"
    if source_dax.exists():
        shutil.copy(source_dax, out / "measures.dax")
        written["measures"] = str((out / "measures.dax").relative_to(cfg.root)) \
            if str(out).startswith(str(cfg.root)) else str(out / "measures.dax")

    return written
