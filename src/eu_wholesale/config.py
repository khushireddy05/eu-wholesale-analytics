"""Configuration loading and path handling.

A single :class:`Config` object is threaded through every pipeline stage so
that paths, the calendar window and model parameters are defined in exactly
one place (``config/config.yaml``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@dataclass
class Config:
    """Typed accessor over the YAML run configuration."""

    raw: dict[str, Any] = field(repr=False)
    root: Path = PROJECT_ROOT

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(raw=data)

    # --------------------------------------------------------------- section
    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})

    @property
    def project(self) -> dict[str, Any]:
        return self.raw["project"]

    @property
    def generation(self) -> dict[str, Any]:
        return self.raw["generation"]

    @property
    def forecasting(self) -> dict[str, Any]:
        return self.raw["forecasting"]

    @property
    def scenarios(self) -> dict[str, Any]:
        return self.raw["scenarios"]

    @property
    def ai(self) -> dict[str, Any]:
        return self.raw["ai"]

    @property
    def seed(self) -> int:
        return int(self.project["random_seed"])

    @property
    def currency(self) -> str:
        return self.project.get("reporting_currency", "EUR")

    # -------------------------------------------------------------- calendar
    @property
    def history_start(self) -> pd.Period:
        return pd.Period(self.raw["calendar"]["history_start"], freq="M")

    @property
    def history_end(self) -> pd.Period:
        return pd.Period(self.raw["calendar"]["history_end"], freq="M")

    @property
    def horizon(self) -> int:
        return int(self.raw["calendar"]["forecast_horizon_months"])

    @cached_property
    def history_months(self) -> pd.PeriodIndex:
        return pd.period_range(self.history_start, self.history_end, freq="M")

    @cached_property
    def forecast_months(self) -> pd.PeriodIndex:
        start = self.history_end + 1
        return pd.period_range(start, periods=self.horizon, freq="M")

    # ----------------------------------------------------------------- paths
    def path(self, key: str) -> Path:
        """Resolve a configured directory, creating it if needed."""
        p = self.root / self.raw["paths"][key]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def file(self, key: str, filename: str) -> Path:
        return self.path(key) / filename
