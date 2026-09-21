"""Command line interface.

    python -m eu_wholesale.cli all          # run the whole pipeline
    python -m eu_wholesale.cli generate     # synthetic dataset
    python -m eu_wholesale.cli build        # validate + build the star schema
    python -m eu_wholesale.cli forecast     # backtest, select, forecast, scenarios
    python -m eu_wholesale.cli insights     # AI-assisted commentary
    python -m eu_wholesale.cli report       # Excel management workbook
    python -m eu_wholesale.cli powerbi      # Power BI hand-off package
    python -m eu_wholesale.cli summary      # print headline results to the terminal
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable

from .config import Config


def _banner(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m", flush=True)


def _done(label: str, started: float) -> None:
    print(f"  done in {time.time() - started:.1f}s  ({label})", flush=True)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_generate(cfg: Config) -> None:
    from . import pipeline
    _banner("1/6  Generating the synthetic wholesale dataset")
    t = time.time()
    written = pipeline.stage_generate(cfg)
    for name, path in written.items():
        print(f"  {name:24s} -> {path}")
    _done("raw layer", t)


def cmd_build(cfg: Config) -> None:
    from . import pipeline
    _banner("2/6  Validating and building the analytical model")
    t = time.time()
    model = pipeline.stage_build(cfg)
    report = model["validation_report"]
    passed = int((report["status"] == "PASS").sum())
    print(f"  data contracts: {passed}/{len(report)} passed")
    failed = report[report["status"] == "FAIL"]
    for r in failed.itertuples():
        print(f"    FAIL  {r.check}: {r.detail}")
    print(f"  mart_market   {model['mart_market'].shape[0]:>7,} rows")
    print(f"  mart_customer {model['mart_customer'].shape[0]:>7,} rows")
    _done("processed layer", t)


def cmd_forecast(cfg: Config) -> None:
    from . import pipeline
    _banner("3/6  Backtesting models and building the forecast")
    print("  fitting candidates across rolling origins (this takes a couple of minutes)")
    t = time.time()
    art = pipeline.stage_forecast(cfg)
    meta = art.meta
    print(f"  champion       {meta['champion_model']}")
    print(f"  WAPE           {meta['champion_wape']:.2f}%  "
          f"(benchmark {meta['benchmark_wape']:.2f}%, "
          f"{meta['improvement_vs_benchmark_pct']:.0f}% better)")
    print(f"  forecast rows  {len(art.forecast):,} at {' x '.join(meta['forecast_grain'])}")
    _done("forecast artifacts", t)


def cmd_insights(cfg: Config) -> None:
    from . import pipeline
    from .ai.insights import generate_insights, write_insights
    _banner("4/6  Generating market commentary")
    t = time.time()
    art = pipeline.load_artifacts(cfg)
    result = generate_insights(art)
    written = write_insights(art, result)
    print(f"  writer         {result.generator}"
          + (f" ({result.model})" if result.generator == "claude" else ""))
    if result.note:
        print(f"  note           {result.note}")
    print(f"  evidence pack  {len(result.evidence)} facts")
    print(f"  verification   {len(result.verification)} figures checked, "
          f"{result.unsupported_count} unsupported")
    for name, path in written.items():
        print(f"  {name:14s} -> {path}")
    _done("commentary", t)


def cmd_report(cfg: Config) -> None:
    from . import pipeline
    from .reporting.management_report import build_excel_report
    _banner("5/6  Building the Excel management report")
    t = time.time()
    art = pipeline.load_artifacts(cfg)
    path = build_excel_report(art)
    print(f"  workbook       -> {path}")
    _done("Excel report", t)


def cmd_powerbi(cfg: Config) -> None:
    from . import pipeline
    from .reporting.powerbi_export import export_powerbi
    _banner("6/6  Exporting the Power BI package")
    t = time.time()
    art = pipeline.load_artifacts(cfg)
    written = export_powerbi(art)
    print(f"  {len(written)} files -> {cfg.path('powerbi').relative_to(cfg.root)}/")
    _done("Power BI package", t)


def cmd_tableau(cfg: Config) -> None:
    from . import pipeline
    from .reporting.tableau_export import export_tableau
    _banner("Exporting the Tableau Public package")
    t = time.time()
    art = pipeline.load_artifacts(cfg)
    written = export_tableau(art)
    print(f"  {len(written)} files -> outputs/tableau/")
    _done("Tableau package", t)


def cmd_summary(cfg: Config) -> None:
    from . import pipeline
    from . import kpis
    from .forecasting.scenarios import scenario_spread, scenario_summary

    art = pipeline.load_artifacts(cfg)
    mart = art.mart_market
    head = kpis.headline_kpis(mart)
    summary = scenario_summary(art.scenarios, mart)
    spread = scenario_spread(summary)

    _banner(f"{cfg.project['name']}")
    print(f"  actuals {cfg.history_start} to {cfg.history_end}   "
          f"forecast {cfg.forecast_months[0]} to {cfg.forecast_months[-1]}\n")
    for r in head.itertuples():
        if r.kpi.endswith("%") or "share" in r.kpi or "CAGR" in r.kpi:
            print(f"  {r.kpi:28s} {r.current_12m:>10.2f}")
        else:
            print(f"  {r.kpi:28s} {r.current_12m:>10,.1f}"
                  + (f"   {r.delta_pct:+.1%} YoY" if r.delta_pct == r.delta_pct else ""))
    print(f"\n  Forecast (baseline)          {spread['baseline_eur'] / 1e6:>10,.1f} EUR m")
    print(f"  Scenario planning range      {spread['spread_eur'] / 1e6:>10,.1f} EUR m "
          f"({spread['spread_pct_of_baseline']:.1%} of baseline)")
    print(f"  Champion model               {art.meta['champion_model']} "
          f"(WAPE {art.meta['champion_wape']:.2f}%, "
          f"{art.meta['improvement_vs_benchmark_pct']:.0f}% better than benchmark)")


def cmd_all(cfg: Config) -> None:
    total = time.time()
    cmd_generate(cfg)
    cmd_build(cfg)
    cmd_forecast(cfg)
    cmd_insights(cfg)
    cmd_report(cfg)
    cmd_powerbi(cfg)
    print(f"\n\033[1mPipeline complete in {time.time() - total:.0f}s.\033[0m")
    cmd_summary(cfg)


COMMANDS: dict[str, Callable[[Config], None]] = {
    "all": cmd_all,
    "generate": cmd_generate,
    "build": cmd_build,
    "forecast": cmd_forecast,
    "insights": cmd_insights,
    "report": cmd_report,
    "powerbi": cmd_powerbi,
    "tableau": cmd_tableau,
    "summary": cmd_summary,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eu_wholesale.cli",
        description="EU wholesale market analytics and forecasting pipeline.")
    parser.add_argument("command", choices=sorted(COMMANDS), help="pipeline stage to run")
    parser.add_argument("--config", default=None, help="path to a config YAML")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    try:
        COMMANDS[args.command](cfg)
    except FileNotFoundError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
