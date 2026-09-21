"""Pipeline stages and artifact handling.

Each stage writes its output to disk so the expensive step (the rolling-origin
backtest) is paid once and the reporting, Power BI and AI stages can be re-run
in seconds against exactly the same numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import Config
from .data.generate import generate_dataset, write_dataset
from .forecasting.run import combine_actual_forecast, run_forecast
from .forecasting.scenarios import build_scenarios
from .model.build import build_model, load_model

FORECAST_TABLES = ("fact_forecast", "fact_scenario", "actual_vs_forecast",
                   "accuracy_by_model", "accuracy_by_horizon",
                   "accuracy_by_product", "accuracy_by_country",
                   "backtest_predictions")


@dataclass
class Artifacts:
    """Everything the reporting and AI layers need, already computed."""

    cfg: Config
    tables: dict[str, pd.DataFrame]
    forecast: pd.DataFrame
    scenarios: pd.DataFrame
    actual_vs_forecast: pd.DataFrame
    accuracy: dict[str, pd.DataFrame]
    meta: dict

    @property
    def mart_market(self) -> pd.DataFrame:
        return self.tables["mart_market"]

    @property
    def mart_customer(self) -> pd.DataFrame:
        return self.tables["mart_customer"]

    @property
    def champion(self) -> str:
        return self.meta["champion_model"]


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def stage_generate(cfg: Config) -> dict[str, str]:
    dataset = generate_dataset(cfg)
    return write_dataset(cfg, dataset)


def stage_build(cfg: Config) -> dict[str, pd.DataFrame]:
    return build_model(cfg, strict=True)


def stage_forecast(cfg: Config) -> Artifacts:
    tables = load_model(cfg)
    mart = tables["mart_market"]

    result = run_forecast(cfg, mart)
    scenarios = build_scenarios(cfg, result.forecast)
    avf = combine_actual_forecast(mart, result.forecast,
                                  keys=tuple(cfg.forecasting["grain"]),
                                  target=cfg.forecasting["target"])

    out = cfg.path("forecast")
    frames = {
        "fact_forecast": result.forecast,
        "fact_scenario": scenarios.assign(scenario=scenarios["scenario"].astype(str)),
        "actual_vs_forecast": avf,
        "accuracy_by_model": result.metrics_overall,
        "accuracy_by_horizon": result.metrics_horizon,
        "accuracy_by_product": result.metrics_product,
        "accuracy_by_country": result.metrics_country,
        "backtest_predictions": result.predictions,
    }
    for name, frame in frames.items():
        frame.to_parquet(out / f"{name}.parquet", index=False)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "champion_model": result.champion,
        "selection_metric": cfg.forecasting["selection_metric"],
        "candidate_models": list(cfg.forecasting["models"]),
        "backtest_origins": result.origins,
        "history_start": str(cfg.history_start),
        "history_end": str(cfg.history_end),
        "horizon_months": cfg.horizon,
        "forecast_grain": list(cfg.forecasting["grain"]),
        "target": cfg.forecasting["target"],
        "champion_wape": float(
            result.metrics_overall.set_index("model").loc[result.champion, "wape"]),
        "benchmark_wape": float(
            result.metrics_overall.set_index("model").loc["seasonal_naive", "wape"]),
    }
    meta["improvement_vs_benchmark_pct"] = (
        (meta["benchmark_wape"] - meta["champion_wape"]) / meta["benchmark_wape"] * 100
    )
    (out / "forecast_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return Artifacts(
        cfg=cfg, tables=tables, forecast=result.forecast, scenarios=scenarios,
        actual_vs_forecast=avf,
        accuracy={k: v for k, v in frames.items() if k.startswith("accuracy")
                  or k == "backtest_predictions"},
        meta=meta,
    )


def load_artifacts(cfg: Config) -> Artifacts:
    """Load previously computed pipeline outputs."""
    out = cfg.path("forecast")
    meta_path: Path = out / "forecast_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            "Forecast artifacts not found - run "
            "'python -m eu_wholesale.cli forecast' first."
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    frames = {name: pd.read_parquet(out / f"{name}.parquet") for name in FORECAST_TABLES}

    scenarios = frames["fact_scenario"]
    from .forecasting.scenarios import SCENARIO_ORDER
    scenarios["scenario"] = pd.Categorical(scenarios["scenario"],
                                           categories=list(SCENARIO_ORDER), ordered=True)

    return Artifacts(
        cfg=cfg, tables=load_model(cfg), forecast=frames["fact_forecast"],
        scenarios=scenarios, actual_vs_forecast=frames["actual_vs_forecast"],
        accuracy={k: v for k, v in frames.items()
                  if k.startswith("accuracy") or k == "backtest_predictions"},
        meta=meta,
    )
