# EU Wholesale Market Analytics & AI Forecasting

An end-to-end analytics prototype for a multi-country EU wholesale carrier
business: a consistent data model across customers, products and market
indicators; Python trend and forecasting workflows with a backtested model
comparison; Excel and Power BI reporting with market, country, customer and
period drill-downs; and an AI-assisted commentary layer that is confined to
deterministic, pre-computed facts.

```
Python (pandas, scikit-learn)  ->  data model + KPIs + forecast + scenarios
        |                                    |
        v                                    v
   Excel workbook                    Power BI package
   (native charts,                   (star schema, DAX
    drill-downs)                      measures, build guide)
        |
        v
   AI market commentary (Claude, evidence-pack constrained + verified)
```

## Quick start

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .

.venv/bin/python -m eu_wholesale.cli all
```

This regenerates everything: the synthetic dataset, the validated analytical
model, the forecast and scenarios, the AI commentary (or its deterministic
fallback), the Excel report and the Power BI package. A full run takes
roughly 2 minutes, most of it the rolling-origin backtest.

Run one stage at a time with `generate`, `build`, `forecast`, `insights`,
`report`, `powerbi`, or print the headline numbers with `summary`. See
`python -m eu_wholesale.cli --help`.

## What's in the box

| Path | Contents |
|---|---|
| `config/config.yaml` | Every run parameter: calendar window, forecast grain, model candidates, scenario assumptions, AI settings |
| `src/eu_wholesale/data/` | Reference data (markets, products, segments) and the synthetic dataset generator |
| `src/eu_wholesale/model/` | Star-schema build and data contract validation |
| `src/eu_wholesale/kpis.py` | Growth, price/volume bridge, concentration and retention calculations |
| `src/eu_wholesale/forecasting/` | Feature engineering, model candidates, rolling-origin backtest, scenario engine |
| `src/eu_wholesale/reporting/` | Excel workbook builder and Power BI export |
| `src/eu_wholesale/ai/` | Evidence-pack construction and the verified AI commentary layer |
| `powerbi/measures.dax` | The DAX measure library, ready to paste into Power BI Desktop |
| `outputs/` | Everything the pipeline produces (gitignored - regenerate with `cli all`) |
| `tests/` | 62 tests covering generation, validation, KPI arithmetic, forecast leakage, and the deliverables |

## The data

The dataset is **synthetic** - 13 EU markets, a 7-product wholesale carrier
portfolio (international voice, A2P messaging, IPX roaming, IP transit,
Ethernet capacity, cloud connect, voice firewall), ~120 customer accounts and
90 months of monthly actuals. It is generated from documented structural
assumptions (`src/eu_wholesale/data/reference.py`,
`src/eu_wholesale/data/generate.py`) - OTT substitution eroding voice, e-commerce
driving A2P, the 2020-21 travel collapse and recovery in roaming, capacity
volume growth against price deflation - not sampled noise, so trends,
seasonality and forecast accuracy are all meaningful. No real customer or
commercial data is used anywhere.

## Forecasting approach

Direct multi-horizon regression at market x product grain: a separate model
per horizon (1-12 months out), trained only on information available at the
forecast origin. Four candidates - seasonal-naive, ridge, elastic-net,
gradient boosting - are compared by rolling-origin backtest (WAPE, MAPE,
sMAPE, bias); the champion is refit on full history and used for the live
forecast. Prediction intervals come from the empirical distribution of
backtest errors by horizon, not a distributional assumption. See
`src/eu_wholesale/forecasting/` and the `Forecast Accuracy` sheet in the
Excel report for the full comparison.

Scenarios (baseline / upside / downside) are explicit price- and
volume-driver adjustments layered on the statistical forecast - never a
separate model fit - so the split between "what the data says" and "what if
the market moves" stays legible.

## The AI layer

The AI stage never sees raw data and performs no arithmetic. A deterministic
evidence pack of ~100 numbered facts (`src/eu_wholesale/ai/evidence.py`) is
built first from validated KPI calculations; the model is instructed to
restate and connect those facts, citing a fact ID after every number. The
output is then re-parsed and every figure is checked against the pack
(`verify_narrative` in `src/eu_wholesale/ai/insights.py`) - unsupported
numbers are reported, not silently published. Without Anthropic credentials
configured, a rule-based writer built from the same evidence pack produces
the commentary instead, so the pipeline never depends on network access to
finish. To enable the model-written version: `ant auth login`, or set
`ANTHROPIC_API_KEY`.

## Testing

```bash
.venv/bin/python -m pytest
```

Runs against a small in-memory configuration (25 customers, 5-year window)
so the full suite - including an actual model fit and backtest - finishes in
well under a minute. Coverage includes: dataset reproducibility and
structural dynamics, data contract pass/fail behaviour, KPI and revenue-bridge
arithmetic, forecast feature leakage (lag and seasonal-naive features are
checked cell-by-cell against the source panel), backtest origin discipline,
scenario ordering, and that every produced deliverable (Excel sheets and
charts, Power BI relationships) is actually present and internally
consistent.
