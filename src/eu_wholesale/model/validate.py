"""Data contracts for the analytical model.

Every stage downstream of the raw layer assumes a set of invariants. Rather
than trusting them, they are asserted explicitly and the result is written out
as a validation report that ships with the deliverables - the reporting and AI
layers only ever consume data that has passed these checks.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CheckResult:
    check: str
    severity: str      # ERROR | WARNING
    passed: bool
    detail: str


class ValidationError(RuntimeError):
    """Raised when a blocking data contract is violated."""


def _fail_count(mask: pd.Series) -> int:
    return int(mask.sum())


def validate_tables(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Run all data contracts and return the report as a frame."""
    fact = tables["fact_traffic"]
    dim_date = tables["dim_date"]
    dim_country = tables["dim_country"]
    dim_product = tables["dim_product"]
    dim_customer = tables["dim_customer"]
    indicators = tables["fact_market_indicator"]

    results: list[CheckResult] = []

    def check(name: str, passed: bool, detail: str, severity: str = "ERROR") -> None:
        results.append(CheckResult(name, severity, bool(passed), detail))

    # ---- completeness ---------------------------------------------------
    key_cols = ["year_month", "customer_id", "country_code", "product_id"]
    nulls = int(fact[key_cols].isna().sum().sum())
    check("fact.keys_not_null", nulls == 0, f"{nulls} null key values")

    dup = _fail_count(fact.duplicated(subset=key_cols))
    check("fact.grain_unique", dup == 0,
          f"{dup} duplicate rows at month x customer x product")

    # ---- referential integrity -----------------------------------------
    for col, dim, name in [
        ("year_month", dim_date, "dim_date"),
        ("country_code", dim_country, "dim_country"),
        ("product_id", dim_product, "dim_product"),
        ("customer_id", dim_customer, "dim_customer"),
    ]:
        orphans = _fail_count(~fact[col].isin(dim[col]))
        check(f"fact.fk_{name}", orphans == 0, f"{orphans} rows with no {name} match")

    # ---- value ranges ---------------------------------------------------
    check("fact.revenue_positive", _fail_count(fact["revenue_eur"] <= 0) == 0,
          f"{_fail_count(fact['revenue_eur'] <= 0)} non-positive revenue rows")
    check("fact.volume_positive", _fail_count(fact["volume_units"] <= 0) == 0,
          f"{_fail_count(fact['volume_units'] <= 0)} non-positive volume rows")
    check("fact.price_positive", _fail_count(fact["unit_price_eur"] <= 0) == 0,
          f"{_fail_count(fact['unit_price_eur'] <= 0)} non-positive unit prices")
    bad_margin = _fail_count((fact["margin_pct"] < -0.5) | (fact["margin_pct"] > 0.95))
    check("fact.margin_pct_in_range", bad_margin == 0,
          f"{bad_margin} rows with implausible gross margin")

    # Revenue must equal volume x price to rounding tolerance.
    recomputed = fact["volume_units"] * fact["unit_price_eur"]
    rel_err = ((recomputed - fact["revenue_eur"]).abs()
               / fact["revenue_eur"].clip(lower=1e-9))
    check("fact.revenue_equals_volume_x_price", bool((rel_err < 0.02).all()),
          f"max relative deviation {rel_err.max():.4%}", severity="WARNING")

    # margin = revenue - cost, exactly.
    margin_err = (fact["revenue_eur"] - fact["cost_eur"] - fact["margin_eur"]).abs().max()
    check("fact.margin_identity", margin_err < 0.05, f"max absolute deviation EUR {margin_err:.4f}")

    # ---- calendar coverage ----------------------------------------------
    # dim_date spans history plus the forecast horizon (so forecast rows have
    # a date to join to); the fact table only ever covers history.
    months_in_fact = fact["year_month"].nunique()
    fact_months_known = set(fact["year_month"].unique()) <= set(dim_date["year_month"])
    check("calendar.full_coverage",
          fact_months_known and months_in_fact <= len(dim_date),
          f"{months_in_fact} distinct fact months, all present in dim_date "
          f"({len(dim_date)} months total)")

    # ---- indicator panel -------------------------------------------------
    # Indicators are only observed for history - dim_date additionally spans
    # the forecast horizon, so the panel is sized off history months.
    n_history_months = fact["year_month"].nunique()
    expected = len(dim_country) * n_history_months
    check("indicators.complete_panel", len(indicators) == expected,
          f"{len(indicators)} rows, expected {expected} "
          f"({len(dim_country)} markets x {n_history_months} history months)")
    ind_nulls = int(indicators.isna().sum().sum())
    check("indicators.no_nulls", ind_nulls == 0, f"{ind_nulls} null values")

    # ---- business plausibility ------------------------------------------
    active = fact["customer_id"].nunique()
    check("customers.all_transacting", active == len(dim_customer),
          f"{active} of {len(dim_customer)} customers have traffic", severity="WARNING")

    report = pd.DataFrame([r.__dict__ for r in results])
    report["status"] = report["passed"].map({True: "PASS", False: "FAIL"})
    return report[["check", "severity", "status", "detail"]]


def assert_valid(report: pd.DataFrame) -> None:
    """Raise if any blocking (ERROR severity) contract failed."""
    blocking = report[(report["severity"] == "ERROR") & (report["status"] == "FAIL")]
    if not blocking.empty:
        lines = "\n".join(f"  - {r.check}: {r.detail}" for r in blocking.itertuples())
        raise ValidationError(f"{len(blocking)} blocking data contract failure(s):\n{lines}")
