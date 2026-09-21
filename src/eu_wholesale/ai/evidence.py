"""Evidence pack construction for the AI analysis workflow.

The AI layer never touches raw data and never performs arithmetic. It is given
this pack: a flat list of numbered, pre-computed facts, each carrying its value,
unit and the table it came from. The model's only job is to select, connect and
explain - which is what language models are good at - while every number in the
output traces back to a deterministic calculation that has already passed the
data contracts.

That boundary is the point. It is also enforced afterwards: see
:func:`eu_wholesale.ai.insights.verify_narrative`.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .. import kpis
from ..forecasting.scenarios import scenario_spread, scenario_summary
from ..pipeline import Artifacts

M = 1e6


@dataclass
class Fact:
    fact_id: str
    category: str
    statement: str
    value: float
    unit: str
    source: str

    def as_line(self) -> str:
        return f"[{self.fact_id}] {self.statement} = {_fmt(self.value, self.unit)} (source: {self.source})"


def _fmt(value: float, unit: str) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    if unit == "EUR m":
        return f"EUR {value:,.1f}m"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "pp":
        return f"{value:+.1f}pp"
    if unit == "index":
        return f"{value:,.1f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


class EvidenceBuilder:
    """Accumulates facts with stable identifiers."""

    def __init__(self) -> None:
        self.facts: list[Fact] = []

    def add(self, category: str, statement: str, value, unit: str, source: str) -> Fact:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            value = float("nan")
        fact = Fact(f"F{len(self.facts) + 1:03d}", category, statement,
                    float(value), unit, source)
        self.facts.append(fact)
        return fact

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(f) for f in self.facts])

    def as_text(self) -> str:
        lines: list[str] = []
        current = None
        for fact in self.facts:
            if fact.category != current:
                current = fact.category
                lines.append(f"\n## {current}")
            lines.append(fact.as_line())
        return "\n".join(lines).strip()


def build_evidence(art: Artifacts) -> EvidenceBuilder:
    """Compute every number the narrative is allowed to use."""
    ev = EvidenceBuilder()
    mart = art.mart_market
    mc = art.mart_customer
    products = art.tables["dim_product"].set_index("product_id")["product_name"].to_dict()
    countries = art.tables["dim_country"].set_index("country_code")["country_name"].to_dict()
    months = sorted(mart["year_month"].unique())
    last_12, prior_12 = months[-12:], months[-24:-12]

    # ---- group performance ---------------------------------------------
    cur = mart[mart["year_month"].isin(last_12)]
    pri = mart[mart["year_month"].isin(prior_12)]
    rev_cur, rev_pri = cur["revenue_eur"].sum(), pri["revenue_eur"].sum()
    mar_cur, mar_pri = cur["margin_eur"].sum(), pri["margin_eur"].sum()

    src = "mart_market"
    ev.add("Group performance", "Revenue, last 12 months", rev_cur / M, "EUR m", src)
    ev.add("Group performance", "Revenue, prior 12 months", rev_pri / M, "EUR m", src)
    ev.add("Group performance", "Revenue growth year on year",
           (rev_cur / rev_pri - 1) * 100, "%", src)
    ev.add("Group performance", "Gross margin, last 12 months", mar_cur / M, "EUR m", src)
    ev.add("Group performance", "Gross margin percentage, last 12 months",
           mar_cur / rev_cur * 100, "%", src)
    ev.add("Group performance", "Gross margin percentage change year on year",
           (mar_cur / rev_cur - mar_pri / rev_pri) * 100, "pp", src)
    first_12 = mart[mart["year_month"].isin(months[:12])]["revenue_eur"].sum()
    ev.add("Group performance", "Revenue CAGR across the observed window",
           kpis.cagr(first_12, rev_cur, (len(months) - 12) / 12) * 100, "%", src)

    # ---- product performance --------------------------------------------
    prod = kpis.yoy_table(mart, "product_id")
    for _, r in prod.iterrows():
        name = products.get(r["product_id"], r["product_id"])
        ev.add("Product performance", f"{name} revenue, last 12 months",
               r["current_12m"] / M, "EUR m", src)
        ev.add("Product performance", f"{name} revenue growth year on year",
               r["delta_pct"] * 100, "%", src)
        ev.add("Product performance", f"{name} share of group revenue",
               r["share_pct"] * 100, "%", src)

    # ---- revenue bridge --------------------------------------------------
    bridge = kpis.price_volume_bridge(mart, ["product_id"])
    ev.add("Revenue bridge", "Total volume effect on revenue year on year",
           bridge["volume_effect"].sum() / M, "EUR m", "price_volume_bridge")
    ev.add("Revenue bridge", "Total price effect on revenue year on year",
           bridge["price_effect"].sum() / M, "EUR m", "price_volume_bridge")
    ev.add("Revenue bridge", "Total joint volume-price effect year on year",
           bridge["joint_effect"].sum() / M, "EUR m", "price_volume_bridge")
    for _, r in bridge.iterrows():
        name = products.get(r["product_id"], r["product_id"])
        ev.add("Revenue bridge", f"{name} volume effect",
               r["volume_effect"] / M, "EUR m", "price_volume_bridge")
        ev.add("Revenue bridge", f"{name} price effect",
               r["price_effect"] / M, "EUR m", "price_volume_bridge")

    # ---- markets ---------------------------------------------------------
    ctry = kpis.yoy_table(mart, "country_code")
    for _, r in ctry.head(6).iterrows():
        name = countries.get(r["country_code"], r["country_code"])
        ev.add("Market performance", f"{name} revenue, last 12 months",
               r["current_12m"] / M, "EUR m", src)
        ev.add("Market performance", f"{name} revenue growth year on year",
               r["delta_pct"] * 100, "%", src)
    best = ctry.nlargest(1, "delta_abs").iloc[0]
    worst = ctry.nsmallest(1, "delta_abs").iloc[0]
    ev.add("Market performance",
           f"Largest absolute market gain: {countries.get(best['country_code'])}",
           best["delta_abs"] / M, "EUR m", src)
    ev.add("Market performance",
           f"Largest absolute market decline: {countries.get(worst['country_code'])}",
           worst["delta_abs"] / M, "EUR m", src)

    # ---- portfolio structure --------------------------------------------
    conc = kpis.concentration(mc)
    ev.add("Portfolio structure", "Active accounts in the last 12 months",
           conc["n"], "count", "mart_customer")
    ev.add("Portfolio structure", "Share of revenue from the ten largest accounts",
           conc["top_10_share"] * 100, "%", "mart_customer")
    ev.add("Portfolio structure", "Customer Herfindahl-Hirschman index",
           conc["hhi"], "index", "mart_customer")
    ev.add("Portfolio structure", "Net revenue retention",
           kpis.net_revenue_retention(mc) * 100, "%", "mart_customer")
    ev.add("Portfolio structure", "Accounts that churned during the window",
           int((art.tables["dim_customer"]["status"] == "Churned").sum()),
           "count", "dim_customer")

    movers = kpis.yoy_table(mc, "customer_id")
    names = art.tables["dim_customer"].set_index("customer_id")
    for _, r in movers.nlargest(3, "delta_abs").iterrows():
        rec = names.loc[r["customer_id"]]
        ev.add("Account movements",
               f"Largest growing account {rec['customer_name']} ({rec['country_code']}, "
               f"{rec['segment']}) revenue change year on year",
               r["delta_abs"] / M, "EUR m", "mart_customer")
    for _, r in movers.nsmallest(3, "delta_abs").iterrows():
        rec = names.loc[r["customer_id"]]
        ev.add("Account movements",
               f"Largest declining account {rec['customer_name']} ({rec['country_code']}, "
               f"{rec['segment']}) revenue change year on year",
               r["delta_abs"] / M, "EUR m", "mart_customer")

    # ---- market indicators ----------------------------------------------
    ind_src = "fact_market_indicator"
    ind = art.tables["fact_market_indicator"]
    latest, base = months[-1], months[-13]
    for col, label in (("travel_index", "International travel index"),
                       ("data_traffic_index", "Data traffic index"),
                       ("ott_substitution_index", "OTT substitution index"),
                       ("ecommerce_index", "E-commerce activity index"),
                       ("cpi_yoy", "Consumer price inflation")):
        cur_v = ind.loc[ind["year_month"] == latest, col].mean()
        base_v = ind.loc[ind["year_month"] == base, col].mean()
        ev.add("Market indicators", f"{label}, EU average, latest month",
               cur_v, "index" if "index" in col else "%", ind_src)
        if "index" in col and base_v:
            ev.add("Market indicators", f"{label} change year on year",
                   (cur_v / base_v - 1) * 100, "%", ind_src)

    # ---- forecast --------------------------------------------------------
    fsrc = "fact_forecast"
    fc_total = art.forecast["forecast_eur"].sum()
    ev.add("Forecast", "Forecast revenue, next 12 months", fc_total / M, "EUR m", fsrc)
    ev.add("Forecast", "Forecast revenue growth versus the last 12 months",
           (fc_total / rev_cur - 1) * 100, "%", fsrc)
    ev.add("Forecast", "Champion model backtest WAPE",
           art.meta["champion_wape"], "%", "accuracy_by_model")
    ev.add("Forecast", "Seasonal-naive benchmark backtest WAPE",
           art.meta["benchmark_wape"], "%", "accuracy_by_model")
    ev.add("Forecast", "Champion accuracy improvement over the benchmark",
           art.meta["improvement_vs_benchmark_pct"], "%", "accuracy_by_model")
    hor = art.accuracy["accuracy_by_horizon"].set_index("horizon")
    for h in (1, 12):
        if h in hor.index:
            ev.add("Forecast", f"Backtest WAPE at a {h}-month horizon",
                   hor.loc[h, "wape"], "%", "accuracy_by_horizon")

    fc_prod = art.forecast.groupby("product_id")["forecast_eur"].sum()
    act_prod = cur.groupby("product_id")["revenue_eur"].sum()
    for pid, val in fc_prod.items():
        name = products.get(pid, pid)
        ev.add("Forecast", f"{name} forecast revenue, next 12 months",
               val / M, "EUR m", fsrc)
        ev.add("Forecast", f"{name} forecast growth versus the last 12 months",
               (val / act_prod.get(pid, np.nan) - 1) * 100, "%", fsrc)

    # ---- scenarios -------------------------------------------------------
    summary = scenario_summary(art.scenarios, mart)
    spread = scenario_spread(summary)
    for _, r in summary.iterrows():
        ev.add("Scenarios", f"{r['scenario']} scenario revenue, next 12 months",
               r["next_12m_eur"] / M, "EUR m", "fact_scenario")
        ev.add("Scenarios", f"{r['scenario']} scenario growth versus the last 12 months",
               r["growth_pct"] * 100, "%", "fact_scenario")
    ev.add("Scenarios", "Planning range between the upside and downside scenarios",
           spread["spread_eur"] / M, "EUR m", "fact_scenario")
    ev.add("Scenarios", "Planning range as a share of the baseline",
           spread["spread_pct_of_baseline"] * 100, "%", "fact_scenario")

    return ev


def context_block(art: Artifacts) -> str:
    """Non-numeric context: what the business is and what the data covers."""
    cfg = art.cfg
    products = art.tables["dim_product"]
    lines = [
        f"Business: multi-country EU wholesale carrier portfolio, "
        f"{art.mart_market['country_code'].nunique()} markets, "
        f"{art.mart_customer['customer_id'].nunique()} carrier and aggregator accounts.",
        f"Actuals cover {cfg.history_start} to {cfg.history_end}. "
        f"The forecast covers {cfg.forecast_months[0]} to {cfg.forecast_months[-1]}.",
        "Product portfolio and lifecycle stage:",
    ]
    for _, p in products.iterrows():
        lines.append(f"  - {p['product_name']} ({p['product_id']}): "
                     f"{p['product_family']}, {p['lifecycle_stage'].lower()} stage, "
                     f"billed per {p['unit']}.")
    lines.append(
        "Known structural drivers in this market: OTT substitution erodes "
        "international voice minutes; A2P messaging termination fees have been "
        "repriced upwards by operators; roaming traffic collapsed during the "
        "2020-21 travel restrictions and has since recovered; IP transit and cloud "
        "connect volumes grow while unit prices deflate; data-centre and AI "
        "workloads have added capacity demand since mid-2024."
    )
    return "\n".join(lines)
