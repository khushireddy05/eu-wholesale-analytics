"""Data contracts must pass on good data and fail loudly on bad data."""

from __future__ import annotations

import pytest

from eu_wholesale.model import validate as v


def test_all_contracts_pass_on_generated_data(model):
    report = model["validation_report"]
    failures = report[report["status"] == "FAIL"]
    assert failures.empty, failures.to_string(index=False)


def test_duplicate_rows_are_detected(dataset):
    tables = {k: f.copy() for k, f in dataset.tables().items()}
    fact = tables["fact_traffic"]
    tables["fact_traffic"] = fact._append(fact.iloc[[0]], ignore_index=True)
    report = v.validate_tables(tables)
    row = report[report["check"] == "fact.grain_unique"].iloc[0]
    assert row["status"] == "FAIL"
    with pytest.raises(v.ValidationError):
        v.assert_valid(report)


def test_orphan_foreign_keys_are_detected(dataset):
    tables = {k: f.copy() for k, f in dataset.tables().items()}
    tables["fact_traffic"].loc[0, "product_id"] = "P99"
    report = v.validate_tables(tables)
    assert report[report["check"] == "fact.fk_dim_product"].iloc[0]["status"] == "FAIL"


def test_broken_margin_identity_is_detected(dataset):
    tables = {k: f.copy() for k, f in dataset.tables().items()}
    tables["fact_traffic"].loc[0, "margin_eur"] += 1000.0
    report = v.validate_tables(tables)
    assert report[report["check"] == "fact.margin_identity"].iloc[0]["status"] == "FAIL"
