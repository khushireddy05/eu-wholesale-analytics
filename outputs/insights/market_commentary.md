# EU Wholesale Market Analytics & AI Forecasting - market commentary

*Actuals to 2026-06. Forecast to 2027-06. Generated 2026-09-01 16:38 UTC.*

*Written by: deterministic rule-based writer. Every figure is drawn from a validated evidence pack of 108 pre-computed facts; the model performs no arithmetic.*

> Note: No Anthropic credentials found - used the deterministic writer. Set ANTHROPIC_API_KEY or run 'ant auth login' for the model-written commentary.

## Executive summary

Revenue over the last twelve months was EUR 2,446.6m [F001], 12.5% [F003] above the prior twelve months, at a gross margin of 28.2% [F005] (+0.3pp [F006] year on year). Across the full observation window revenue has compounded at 8.4% [F007] a year. The champion forecast projects EUR 2,632.6m [F080] for the next twelve months, 7.6% [F081] above the trailing year.

## What drove the year

The year-on-year movement is a volume story offset by continued rate erosion: traffic growth contributed EUR 439.7m [F029] while price movements took EUR 129.3m [F030] out of revenue. That pattern is characteristic of a wholesale portfolio in which capacity and roaming volumes are growing faster than realised prices are falling.

The strongest product movement was Cloud Connect at +22.6% [F021]; the weakest was International Voice Termination at -17.6% [F027]. Voice termination continues to be eroded by OTT substitution, while messaging and roaming benefit from e-commerce activity and the recovery in international travel.

## Forecast outlook

The selected model is gradient_boosting, chosen on rolling-origin backtest accuracy across 4 forecast origins. It records a WAPE of 11.3% [F082] against 14.3% [F083] for the seasonal-naive benchmark, an improvement of 20.9% [F084]. Error widens with horizon, from 6.9% [F085] at one month to 12.7% [F086] at twelve, which is the basis for the widening prediction interval in the pack.

## Scenario risk

The scenario set spans EUR 2,481.6m [F101] to EUR 2,790.9m [F105] against a baseline of EUR 2,632.6m [F103] - a planning range of EUR 309.3m [F107], or 11.7% [F108] of the baseline. The spread is driven by the growth products, where the assumed price and volume adjustments compound over the horizon.

## Where to focus

- Defend realised price where volume growth is strongest: the price effect of EUR 129.3m [F030] is the single largest drag on the year.
- Manage the voice decline for margin rather than volume; it is the only product family in structural contraction.
- Protect the account base: the ten largest accounts carry 31.0% [F061] of revenue.

## Watch items

- Customer concentration: top-10 share of 31.0% [F061] and an HHI of 180.6 [F062].
- Net revenue retention stands at 112.5% [F063], with 11 [F064] accounts churned during the window.
- Forecast error is measured, not assumed: re-run the backtest each month and watch for bias drifting away from zero.

---

## Traceability

- Figures checked against the evidence pack: 26
- Figures not traceable to a fact: 0
- Distinct facts cited: 25
- Full evidence pack: `evidence_pack.csv`. Verification detail: `verification_report.csv`.
