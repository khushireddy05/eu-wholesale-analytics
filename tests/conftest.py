"""Shared fixtures.

Tests run against a deliberately small configuration - fewer customers, a
shorter calendar and a three-month horizon - so the whole suite finishes in
seconds while exercising exactly the same code paths as a full run.
"""

from __future__ import annotations

import copy

import pytest

from eu_wholesale.config import Config
from eu_wholesale.data.generate import generate_dataset, write_dataset
from eu_wholesale.model.build import build_model


@pytest.fixture(scope="session")
def small_config(tmp_path_factory) -> Config:
    root = tmp_path_factory.mktemp("wholesale")
    base = Config.load()
    cfg = Config(raw=copy.deepcopy(base.raw), root=root)
    cfg.raw["calendar"]["history_start"] = "2021-01"
    cfg.raw["calendar"]["history_end"] = "2025-12"
    cfg.raw["calendar"]["forecast_horizon_months"] = 3
    cfg.raw["generation"]["n_customers"] = 25
    cfg.raw["forecasting"]["backtest_folds"] = 2
    cfg.raw["forecasting"]["backtest_step"] = 3
    cfg.raw["forecasting"]["min_train_months"] = 24
    cfg.raw["forecasting"]["models"] = ["seasonal_naive", "ridge"]
    cfg.raw["ai"]["enabled"] = False
    return cfg


@pytest.fixture(scope="session")
def dataset(small_config):
    return generate_dataset(small_config)


@pytest.fixture(scope="session")
def model(small_config, dataset):
    write_dataset(small_config, dataset)
    return build_model(small_config)


@pytest.fixture(scope="session")
def artifacts(small_config, model):
    """Full pipeline artifacts - forecast, scenarios and accuracy tables."""
    from eu_wholesale import pipeline
    return pipeline.stage_forecast(small_config)
