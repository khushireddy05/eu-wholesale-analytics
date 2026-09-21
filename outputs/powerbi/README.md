# Power BI model - build guide

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
