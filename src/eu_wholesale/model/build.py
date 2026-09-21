"""Analysis-ready model build.

Turns the raw tables into the consistent star schema that every downstream
consumer - Python forecasting, the Excel workbook and the Power BI model -
reads from. Two aggregate marts are materialised because they are the grains
the business actually reports on:

  * ``mart_market``   month x country x product  (market / product performance)
  * ``mart_customer`` month x customer x product (account management view)

Aggregates are derived from a single fact table, so every view reconciles to
the same group total by construction.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import Config
from . import validate as v

RAW_TABLES = ("dim_date", "dim_country", "dim_product", "dim_customer",
              "fact_traffic", "fact_market_indicator")


def read_raw(cfg: Config) -> dict[str, pd.DataFrame]:
    raw = cfg.path("raw")
    tables: dict[str, pd.DataFrame] = {}
    for name in RAW_TABLES:
        path: Path = raw / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found - run 'python -m eu_wholesale.cli generate' first."
            )
        tables[name] = pd.read_csv(path, dtype={"churn_month": "string"}
                                   if name == "dim_customer" else None)
    tables["dim_customer"]["churn_month"] = (
        tables["dim_customer"]["churn_month"].fillna("").astype(str)
    )
    return tables


def build_mart_market(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Month x country x product performance mart, enriched with indicators."""
    fact = tables["fact_traffic"]

    agg = (fact.groupby(["year_month", "country_code", "product_id"], as_index=False)
                .agg(volume_units=("volume_units", "sum"),
                     revenue_eur=("revenue_eur", "sum"),
                     cost_eur=("cost_eur", "sum"),
                     margin_eur=("margin_eur", "sum"),
                     active_customers=("customer_id", "nunique")))

    # Realised (volume-weighted) unit price, the correct way to aggregate price.
    agg["unit_price_eur"] = agg["revenue_eur"] / agg["volume_units"]
    agg["margin_pct"] = agg["margin_eur"] / agg["revenue_eur"]
    agg["revenue_per_customer_eur"] = agg["revenue_eur"] / agg["active_customers"]

    agg = (agg.merge(tables["dim_country"], on="country_code", how="left")
              .merge(tables["dim_product"][["product_id", "product_name",
                                            "product_family", "unit",
                                            "lifecycle_stage"]],
                     on="product_id", how="left")
              .merge(tables["dim_date"][["year_month", "date", "year", "quarter",
                                         "quarter_no", "month_no", "month_label"]],
                     on="year_month", how="left")
              .merge(tables["fact_market_indicator"],
                     on=["year_month", "country_code"], how="left"))

    return agg.sort_values(["year_month", "country_code", "product_id"]).reset_index(drop=True)


def build_mart_customer(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Month x customer x product account mart."""
    fact = tables["fact_traffic"]
    cust = tables["dim_customer"][["customer_id", "customer_name", "segment",
                                   "contract_type", "customer_tier", "status",
                                   "is_new_business", "account_size_factor"]]
    out = (fact.merge(cust, on="customer_id", how="left")
                .merge(tables["dim_country"][["country_code", "country_name", "region"]],
                       on="country_code", how="left")
                .merge(tables["dim_product"][["product_id", "product_name",
                                              "product_family", "unit"]],
                       on="product_id", how="left")
                .merge(tables["dim_date"][["year_month", "date", "year", "quarter",
                                           "month_no"]],
                       on="year_month", how="left"))
    return out.sort_values(["year_month", "customer_id", "product_id"]).reset_index(drop=True)


def build_model(cfg: Config, strict: bool = True) -> dict[str, pd.DataFrame]:
    """Validate the raw layer and materialise the analysis-ready model."""
    tables = read_raw(cfg)

    report = v.validate_tables(tables)
    if strict:
        v.assert_valid(report)

    model = dict(tables)
    model["mart_market"] = build_mart_market(tables)
    model["mart_customer"] = build_mart_customer(tables)
    model["validation_report"] = report

    out = cfg.path("processed")
    for name in ("mart_market", "mart_customer"):
        model[name].to_parquet(out / f"{name}.parquet", index=False)
    report.to_csv(out / "validation_report.csv", index=False)
    return model


def load_model(cfg: Config) -> dict[str, pd.DataFrame]:
    """Load a previously built model, building it on demand if missing."""
    processed = cfg.path("processed")
    market = processed / "mart_market.parquet"
    if not market.exists():
        return build_model(cfg)
    tables = read_raw(cfg)
    tables["mart_market"] = pd.read_parquet(market)
    tables["mart_customer"] = pd.read_parquet(processed / "mart_customer.parquet")
    return tables
