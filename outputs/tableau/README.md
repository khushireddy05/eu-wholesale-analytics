# Tableau Public — build guide

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
