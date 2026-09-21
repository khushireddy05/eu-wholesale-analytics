# EU Wholesale Management Report — Workbook Guide

The workbook is a management reporting pack built from synthetic EU wholesale telecom data. It contains 12 worksheets. The main reporting period ends in June 2026, while the forecast runs from July 2026 to June 2027.

A useful distinction:

- “Current 12m” means July 2025–June 2026.
- “Prior 12m” means July 2024–June 2025.
- The 2026 columns in annual tables contain only January–June, so they should not be compared directly with complete previous years.

## 1. Read me

This sheet explains the scope and methodology.

The project covers:

- 13 EU markets
- Seven wholesale telecom products
- 120 synthetic customer accounts
- 90 months of actual data
- A 12-month forecast
- Four forecasting models

The selected forecast model is gradient boosting. Its backtest WAPE is 11.3%, compared with 14.3% for the seasonal-naïve benchmark—approximately 21% better.

Important definitions:

- WAPE: total absolute forecast error divided by total actual revenue. Lower is better.
- Realised unit price: revenue divided by traffic volume.
- Prediction interval: the plausible range around the forecast, based on historical forecast errors.
- Revenue bridge: separates revenue change into volume, price, joint, new-business, and lost-business effects.

This sheet also states that the dataset is entirely synthetic.

---

## 2. KPI Summary

This is the executive overview.

### Headline results

For the 12 months ending June 2026:

- Revenue: €2,446.6 million
- Previous 12 months: €2,174.3 million
- Increase: €272.3 million, or 12.5%
- Gross margin: €690.6 million
- Gross margin growth: 13.9%
- Gross margin percentage: 28.2%
- Previous margin percentage: 27.9%
- Active markets: 13
- Active products: seven
- Revenue CAGR since 2019: 8.4%
- Top-10 customer share: 31.0%

The business is growing, and gross profit is growing slightly faster than revenue. This produces a small improvement in margin percentage.

### Product mix

The biggest product is A2P Messaging:

- Revenue: €781.0 million
- Growth: 21.3%
- Portfolio share: 31.9%

Other major products:

- IPX Roaming: €529.2 million, +13.8%
- Ethernet and Capacity: €424.8 million, +2.2%
- IP Transit: €197.0 million, +17.5%
- Cloud Connect: €189.1 million, +22.6%
- Voice Firewall: €188.8 million, +16.6%
- International Voice: €136.7 million, −17.6%

Cloud Connect is growing fastest, but A2P Messaging creates the largest absolute increase. International Voice is the only declining product.

### Market mix

The largest markets are:

- France: €485.2 million, 19.8% share
- Germany: €457.3 million, 18.7%
- Spain: €394.9 million, 16.1%
- Netherlands: €277.9 million, 11.4%
- Poland: €213.2 million, 8.7%

France, Germany, and Spain together generate about 55% of portfolio revenue.

The two charts on the right visualize rolling-12-month revenue by product and market.

---

## 3. Market View

This sheet explains geographic performance.

### Annual revenue table

It presents revenue for each country from 2019 through 2026.

The strongest markets are France, Germany, Spain, and the Netherlands. Poland and Italy also show meaningful expansion.

Important: the 2026 column contains only six months, through June. It is not evidence of an annual decline.

Examples:

- France grew from €252.4 million in 2019 to €468.7 million in 2025.
- Spain grew from €187.7 million to €368.5 million.
- Germany grew more steadily, from €322.5 million to €433.9 million.
- Croatia remains a very small market.

The line chart shows how market revenue developed over time.

### Market and product-family mix

The second table shows what each country sells:

- Germany is strongest in Internet and Capacity.
- France has particularly strong Messaging and Mobile Data/Roaming revenue.
- Spain has a large Messaging business.
- The Netherlands has a relatively balanced portfolio.
- Some smaller markets do not sell every product family.

This helps identify geographic dependency on particular products.

### Gross margin by market

This section compares revenue, gross margin, margin percentage, and year-on-year movement.

Examples:

- Croatia has the highest percentage margin, but on a very small revenue base.
- Czechia: approximately 32.2%
- Italy: 30.8%
- Romania: 29.9%
- Germany: 29.3%
- France: 28.3%
- Slovakia: 23.2%

Margin percentage should be considered alongside revenue scale. A high-margin small market may contribute less absolute profit than a lower-margin large market.

---

## 4. Product View

This sheet explains portfolio transformation.

### Annual product revenue

The product table shows a clear strategic shift:

- International Voice fell from €499.2 million in 2019 to €151.7 million in 2025.
- A2P Messaging increased from €202.8 million to €707.8 million.
- IPX Roaming recovered strongly after the pandemic.
- Cloud Connect increased from €48.9 million to €174.1 million.
- Voice Firewall increased from €53.0 million to €175.2 million.
- IP Transit and Ethernet also expanded.

Again, 2026 contains only six months.

### Realised unit-price index

Each product starts at 100 in 2019. The index shows how its realised price changed.

Examples:

- IP Transit fell to 19.4 by 2026.
- IPX Roaming fell to 42.5.
- Cloud Connect fell to 50.1.
- Ethernet fell to 57.2.
- International Voice fell to 57.1.
- A2P Messaging increased to 154.1.

This demonstrates that many wholesale data products experience strong price erosion. Their revenue can still grow when traffic increases faster than prices decline.

### Traffic-volume index

This shows volume growth relative to 2019.

Examples:

- IP Transit reached 789 in 2025.
- Cloud Connect reached 663.
- IPX Roaming reached 472.
- Voice Firewall reached 391.
- A2P Messaging reached 232.
- International Voice fell to approximately 51.

This is the central portfolio story: data and connectivity volumes are expanding rapidly, while traditional voice traffic contracts.

The apparent reduction in 2026 indexes is mainly because 2026 contains only half a year.

---

## 5. Customer View

This sheet examines customer structure and concentration.

### Portfolio indicators

- Active accounts in the latest 12 months: 111
- Largest customer share: 4.0%
- Top-10 share: 31.0%
- HHI: 180.6
- Net revenue retention: 112.5%
- Accounts churned during the complete history: 11

An HHI of 180.6 indicates low overall customer concentration. However, 31% of revenue still depends on the ten largest customers, so these accounts deserve focused retention management.

Net revenue retention of 112.5% means the retained customer base produced 12.5% more revenue than in the previous comparable period.

### Revenue by customer segment

The largest segment is Messaging Aggregators:

- Revenue: €590.7 million
- Growth: 23.1%
- Share: 24.1%

Other segments:

- Tier-2 Carrier: €541.9 million
- Tier-1 Carrier: €448.0 million
- Enterprise Aggregator: €377.4 million
- Hyperscaler and OTT: €377.0 million
- MVNO: €111.7 million

### Top accounts

The workbook lists the 25 largest customers with:

- Customer and country
- Segment
- Tier
- Contract type
- Current and previous revenue
- Absolute and percentage growth
- Portfolio share

The largest customer produces €96.9 million, or around 4% of total revenue.

### Largest movers

The final table identifies the ten largest positive and negative customer movements.

For example:

- `CUS0103` increased by €30.8 million, or 87.5%.
- `CUS0010` increased by €17.0 million.
- `CUS0024` declined by €5.9 million, or 97.1%.
- A decline of exactly 100% usually indicates complete churn or lost business.

This is the account-management action list.

---

## 6. Trend & Forecast

This sheet combines historical monthly revenue and the future forecast.

### Actual period

Monthly actual revenue runs from January 2019 through June 2026.

The trend shows:

- General long-term growth
- Monthly seasonality
- Pandemic-related product effects
- Increasing revenue scale in recent years

For example, monthly revenue was generally around €110–€130 million in 2019–2021 and moved towards approximately €170–€200 million during 2024–2026.

### Forecast period

The forecast covers July 2026 through June 2027.

It displays:

- Central forecast
- Lower prediction bound
- Upper prediction bound

The prediction interval represents historically observed forecast uncertainty. It is not a guaranteed minimum and maximum.

The group forecast totals €2,632.6 million over the next 12 months, representing forecast growth of 7.6%.

---

## 7. Scenarios

This sheet converts the baseline forecast into planning cases.

### Assumptions

Baseline:

- No additional price or volume adjustment
- Represents the statistical forecast

Upside:

- Annual price effect: +3%
- Annual volume effect: +6%
- Assumes stronger messaging/IPX demand, slower price erosion, and major customer wins

Downside:

- Annual price effect: −5.5%
- Annual volume effect: −4.5%
- Assumes faster voice decline, price competition, and churn

The adjustments ramp across the forecast horizon instead of appearing as an immediate one-month jump.

### Group outcomes

- Downside: €2,481.6 million, +1.4%
- Baseline: €2,632.6 million, +7.6%
- Upside: €2,790.9 million, +14.1%

The total planning range is €309.3 million, equal to 11.7% of baseline revenue.

### Product outcomes

The final table shows how each product reacts.

Examples:

- International Voice declines under every scenario.
- A2P Messaging grows between 4.1% and 17.8%.
- IPX Roaming grows between 3.6% and 16.7%.
- Cloud Connect grows between 5.2% and 18.7%.
- Voice Firewall grows between 10.6% and 20.2%.
- Ethernet declines slightly in the downside case.

This shows which products create upside and which ones represent structural risk.

---

## 8. Forecast Accuracy

This sheet explains how the forecasting model was selected.

### Model comparison

Four models were tested:

| Model | WAPE | Interpretation |
|---|---:|---|
| Gradient boosting | 11.3% | Selected champion |
| Seasonal naïve | 14.3% | Benchmark |
| Elastic net | 22.5% | Weaker |
| Ridge | 25.7% | Weakest |

Gradient boosting improved WAPE by 20.9% relative to the benchmark.

### Metric definitions

- MAE: average absolute forecast error in euros.
- RMSE: similar to MAE but penalizes large errors more heavily.
- MAPE: average percentage error; sensitive to small actual values.
- sMAPE: symmetric percentage error.
- WAPE: total absolute error divided by total actual revenue.
- Bias: whether the model systematically forecasts too high or too low.
- N obs: number of backtest observations.

The champion has bias of −2.4%, indicating mild underforecasting overall.

### Accuracy by horizon

WAPE generally increases as the forecast moves further into the future:

- Month 1: 6.9%
- Month 4: 10.8%
- Month 8: 12.9%
- Month 12: 12.7%

This is normal: longer-range forecasts contain greater uncertainty.

### Accuracy by product

- Ethernet: 5.3% WAPE
- IP Transit: 6.7%
- Voice Firewall: 8.3%
- Cloud Connect: 11.1%
- A2P Messaging: 11.7%
- IPX Roaming: 13.0%
- International Voice: 30.4%

International Voice is difficult to forecast because its structural decline and customer changes are less stable.

### Accuracy by country

Best-performing larger markets include:

- Italy: 6.5% WAPE
- Spain: 8.8%
- Germany: 9.0%

Higher-error markets include:

- Croatia: 21.1%
- France and Poland: approximately 15%

Small markets frequently have higher percentage errors because individual customer changes have greater relative impact.

---

## 9. Revenue Bridge

This sheet explains why rolling-12-month revenue changed.

The formula separates the movement into:

- Volume effect: revenue gained or lost because traffic changed
- Price effect: revenue gained or lost because unit price changed
- Joint effect: interaction between simultaneous price and volume changes
- New business: revenue from newly active combinations
- Lost business: revenue removed by discontinued combinations
- Unexplained: reconciliation difference

### Product bridge

Examples:

- A2P Messaging gained €137.1 million:
  - €109.5 million from volume
  - €23.6 million from price
  - €4.0 million from the interaction

- IPX Roaming gained €64.2 million:
  - €135.1 million from volume
  - Offset by −€55.0 million price
  - Offset by −€16.0 million joint effect

- IP Transit gained €29.3 million:
  - €83.1 million from volume
  - Offset by −€36.0 million price
  - Offset by −€17.9 million interaction

- International Voice lost €29.1 million:
  - −€20.0 million from volume
  - −€10.4 million from price

This confirms that portfolio growth is primarily volume-driven, with price erosion affecting many products.

### Market bridge

The market section applies the same structure by country.

However, it should be interpreted cautiously: different products use incompatible physical units—minutes, SMS, GB, Mbps, and subscriptions. Aggregating them into one market-level “volume” or “price” effect can become economically ambiguous. The product-level bridge is more reliable because every row within a product uses the same unit.

The tiny unexplained values such as `-1.49e-14` are floating-point rounding effects and effectively equal zero.

---

## 10. Commentary

This is the management narrative generated from validated facts.

It contains:

- Executive summary
- Explanation of annual revenue drivers
- Forecast outlook
- Scenario risk
- Recommended management focus
- Watch items
- Traceability results

Main narrative:

- Revenue reached €2,446.6 million.
- Growth was 12.5%.
- Gross margin reached 28.2%.
- Volume was the main growth driver.
- Price erosion remained the primary drag.
- Cloud Connect was the fastest-growing product.
- International Voice was the weakest.
- Forecast growth is 7.6%.
- The scenario range is €309.3 million.
- Customer concentration requires monitoring.

The commentary was generated by the deterministic fallback writer because Anthropic credentials were unavailable.

Every referenced number has an evidence ID such as `[F001]`. Verification results show:

- 26 figures checked
- Zero unsupported figures
- 25 distinct evidence facts cited

This means the commentary does not contain invented numbers.

---

## 11. Data – Monthly

This is the detailed analytical table behind the reporting sheets.

It has 6,880 data rows plus headers, at approximately:

```text
month × country × product
```

The columns include:

- Month, year, and quarter
- Country and region
- Product and product family
- Lifecycle stage
- Traffic volume and unit
- Unit price
- Revenue
- Cost
- Margin
- Margin percentage
- Market indicators

This sheet is intended for:

- Excel pivot tables
- Custom filtering
- Reconciliation
- Ad hoc analysis
- Building additional charts

You should not add together traffic volumes across different products because the units differ. For example, SMS cannot be added meaningfully to minutes or gigabytes.

Revenue, cost, and margin can be aggregated across all products because they use the same currency.

---

## 12. Validation

This sheet documents the checks performed before reporting.

All 16 checks passed.

The checks confirm:

- No missing keys
- No duplicate fact-table rows
- All dates match the date dimension
- All countries, products, and customers have valid dimension records
- Revenue, volume, and price are positive
- Margins are within plausible ranges
- Revenue approximately equals volume multiplied by price
- Margin equals revenue minus cost
- All 90 historical months are present
- The market-indicator panel is complete
- No indicator values are missing
- All 120 customers transact at least once

The small revenue-versus-volume-and-price deviation of 0.0066% comes from stored-value rounding. The maximum margin identity deviation is only €0.01.

## Overall business conclusion

The synthetic business is performing well:

- Revenue grew 12.5%.
- Gross profit grew 13.9%.
- Margin improved slightly.
- Growth is being led by messaging, roaming, cloud, IP transit, and security.
- International Voice continues to decline structurally.
- Most growth comes from traffic volume, while unit-price erosion remains a challenge.
- Customer concentration is manageable but important.
- The forecast expects 7.6% growth, with an outcome range from 1.4% to 14.1%.
- Gradient boosting is the strongest tested forecasting model, although International Voice remains difficult to predict.

