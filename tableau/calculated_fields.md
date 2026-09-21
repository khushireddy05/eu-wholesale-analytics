# EU Wholesale Market Analytics — Tableau calculated field library

Tableau equivalent of `powerbi/measures.dax`. Create each field via
**Analysis > Create Calculated Field**, name it exactly as shown (the bold
heading), and paste the formula. Grouped the same way as the DAX file so you
can build them in order.

Data model assumption: `fact_revenue`, `fact_forecast`, `fact_scenario`,
`fact_market_indicator` and `fact_backtest` are each related (not joined) to
`dim_date`, `dim_country`, `dim_product`, `dim_customer` and `dim_scenario` on
their key columns — set this up first in the **Data Source** tab using
Tableau's relationship canvas (drag one table onto another, pick the matching
key). Relationships (not physical joins) keep each fact table at its own grain
and avoid the row-multiplication you'd get from joining facts directly to
each other.

---

## 01 Core

**Revenue**
```
SUM([Revenue Eur])
```

**Cost**
```
SUM([Cost Eur])
```

**Gross Margin**
```
SUM([Margin Eur])
```

**Gross Margin %**
```
SUM([Margin Eur]) / SUM([Revenue Eur])
```
Format as percentage.

**Traffic Volume**
```
SUM([Volume Units])
```

**Realised Unit Price**
```
// Recomputed from aggregates - never average the row-level price field,
// it would weight every row equally regardless of size.
SUM([Revenue Eur]) / SUM([Volume Units])
```

**Active Customers**
```
COUNTD([Customer Id])
```

**Revenue per Customer**
```
[Revenue] / [Active Customers]
```

---

## 02 Time intelligence

Tableau's date-based time intelligence relies on `dim_date.Date` being used
as the axis / context date field, with `Date` set as a proper Date type and
the `fact_revenue` table related to `dim_date` on `year_month`.

**Revenue LY**
```
// Requires a Table Calculation: Compute using "Date" (dim_date), 
// then set to "Lookup" with an offset. Simplest approach - LOD:
{ FIXED DATEADD('year', -1, [Date]) : SUM([Revenue Eur]) }
```
> Note: this LOD pattern needs `[Date]` to exist at row-level granularity in
> the view. If your view is aggregated to month, use a table calculation
> instead: right-click the pill > **Add Table Calculation** > *Difference
> From* > *Previous 12* on a month-level date axis.

**Revenue YoY**
```
[Revenue] - [Revenue LY]
```

**Revenue YoY %**
```
([Revenue] - [Revenue LY]) / [Revenue LY]
```

**Revenue YTD**
```
// Table calculation: Running Total of [Revenue], computed along Date,
// restarting every year (Analysis > Create Calculated Field is not needed -
// configure directly on the pill: Add Table Calculation > Running Total,
// Restarting every "Year of Date").
RUNNING_SUM(SUM([Revenue Eur]))
```

**Revenue R12M**
```
WINDOW_SUM(SUM([Revenue Eur]), -11, 0)
```
Set the table calculation to compute using Date, sorted ascending, at month
granularity.

**Revenue R12M LY**
```
WINDOW_SUM(SUM([Revenue Eur]), -23, -12)
```

**Revenue R12M Growth %**
```
([Revenue R12M] - [Revenue R12M LY]) / [Revenue R12M LY]
```

**Gross Margin % LY**
```
{ FIXED DATEADD('year', -1, [Date]) : SUM([Margin Eur]) }
/ { FIXED DATEADD('year', -1, [Date]) : SUM([Revenue Eur]) }
```

**Gross Margin pp Change**
```
([Gross Margin %] - [Gross Margin % LY]) * 100
```

---

## 03 Mix and concentration

**Revenue Share of Market %**
```
// Table calc: Percent of Total, computed along Country Name
SUM([Revenue Eur]) / TOTAL(SUM([Revenue Eur]))
```
Configure via **Add Table Calculation > Percent of Total**, "Compute using"
= Country Name.

**Revenue Share of Portfolio %**
Same pattern, "Compute using" = Product Name.

**Top 10 Customer Share %**
```
// Set-based approach:
// 1. Right-click Customer Name > Create > Set... > Top tab > By field,
//    Top 10 by SUM(Revenue Eur).
// 2. Drop the set on the filter shelf, or use it in a calc:
IF [Top 10 Customers Set] THEN [Revenue Eur] END
```
Then build a Revenue measure filtered to the set, divided by the unfiltered
total (use an LOD `{ FIXED : SUM([Revenue Eur]) }` for the denominator so
the set filter doesn't also shrink it).

**Customer HHI**
```
// Level of Detail calculation - one row per customer, then aggregate.
{ FIXED [Customer Id] :
    (SUM([Revenue Eur]) / TOTAL(SUM([Revenue Eur]))) ^ 2
} * 10000
```
Sum this LOD result across customers in the view (Tableau will do this by
default when you drop it on a shelf without a customer-level dimension).

**Net Revenue Retention %**
```
// Two-step: 
// 1. Set "Prior Cohort" = customers active { FIXED DATEADD('year',-1,[Date]) }
// 2. NRR = SUM(Revenue Eur) filtered to Prior Cohort, current period
//    / SUM(Revenue Eur) for Prior Cohort, prior period
// Simplest to build as two separate worksheets and combine as a single
// number card via a data blend, or precompute in Python and expose as a
// column (recommended for reliability - see fact_kpi_snapshot.csv).
```

---

## 04 Forecast

**Forecast Revenue**
```
SUM([Forecast Eur])
```
(from `fact_forecast`)

**Forecast Lower / Forecast Upper**
```
SUM([Forecast Lo Eur])
SUM([Forecast Hi Eur])
```

**Revenue and Forecast**
```
IFNULL([Revenue], [Forecast Revenue])
```
Use this as the single line-chart measure so actuals and forecast render as
one continuous line — build it on a blended data source, or union
`fact_revenue` and `fact_forecast` first (see the build guide, step 4).

**Forecast Interval Width %**
```
([Forecast Upper] - [Forecast Lower]) / [Forecast Revenue]
```

---

## 05 Scenarios

**Scenario Revenue**
```
SUM([Forecast Eur])   // from fact_scenario
```

**Baseline Revenue**
```
IF [Scenario] = "Baseline" THEN [Forecast Eur] END
```
Wrap in `SUM()` when placed on a shelf, or use:
```
{ FIXED : SUM(IF [Scenario] = "Baseline" THEN [Forecast Eur] END) }
```

**Scenario vs Baseline**
```
[Scenario Revenue] - [Baseline Revenue]
```

**Scenario vs Baseline %**
```
([Scenario Revenue] - [Baseline Revenue]) / [Baseline Revenue]
```

**Scenario Planning Range**
```
{ FIXED : SUM(IF [Scenario] = "Upside" THEN [Forecast Eur] END) }
- { FIXED : SUM(IF [Scenario] = "Downside" THEN [Forecast Eur] END) }
```

---

## 06 Forecast accuracy

(from `fact_backtest`)

**Backtest Absolute Error**
```
SUM([Abs Error])
```

**Backtest Actual**
```
SUM([Y])
```

**WAPE %**
```
[Backtest Absolute Error] / [Backtest Actual]
```

**Forecast Bias %**
```
SUM([Y Pred] - [Y]) / [Backtest Actual]
```

**Benchmark WAPE %**
```
{ FIXED : SUM(IF [Model] = "seasonal_naive" THEN [Abs Error] END) }
/ { FIXED : SUM(IF [Model] = "seasonal_naive" THEN [Y] END) }
```

**Accuracy Gain vs Benchmark %**
```
([Benchmark WAPE %] - [WAPE %]) / [Benchmark WAPE %]
```

---

## 07 Formatting helpers

**Revenue (EUR m)**
```
[Revenue] / 1000000
```

**Forecast Revenue (EUR m)**
```
[Forecast Revenue] / 1000000
```

**Growth Colour**
```
IF [Revenue YoY %] >= 0 THEN "#1F7A4D" ELSE "#B4232C" END
```
Use in a calculated field mapped to colour via a diverging custom palette, or
simpler: put `Revenue YoY %` on the Colour shelf directly with a
red-green diverging palette centred on 0.

**KPI Trend Label**
```
IF [Revenue R12M Growth %] >= 0.05 THEN "Growing"
ELSEIF [Revenue R12M Growth %] >= 0 THEN "Stable"
ELSEIF [Revenue R12M Growth %] >= -0.05 THEN "Softening"
ELSE "Declining"
END
```

---

## Notes on things that are easier in Python than in Tableau

A few DAX measures (Net Revenue Retention, HHI, concentration) rely on
per-customer set logic that is straightforward in DAX/pandas but fiddly in
Tableau's calculation language. Rather than fighting Tableau's LOD syntax for
these, the export includes a pre-computed `fact_kpi_snapshot.csv` with NRR,
HHI and concentration already calculated per month — drop those columns
straight onto a number-card worksheet instead of rebuilding the logic in
Tableau. This is the same principle the whole project follows: calculations
happen once, deterministically, in Python; the BI tool visualises them.
