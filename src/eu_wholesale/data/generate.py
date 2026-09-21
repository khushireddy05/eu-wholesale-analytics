"""Synthetic EU wholesale dataset generation.

Builds a reproducible, business-plausible dataset for a multi-country
wholesale carrier business:

  * ``dim_date``      - monthly calendar with fiscal attributes
  * ``dim_country``   - the 13 EU markets in scope
  * ``dim_product``   - the wholesale product portfolio
  * ``dim_customer``  - anonymised carrier / aggregator accounts
  * ``fact_traffic``  - month x customer x product traffic, revenue, cost, margin
  * ``fact_market_indicator`` - month x country macro / market indicators

The demand model is deliberately multiplicative and fully documented so every
movement in the data can be traced back to a stated business driver:

    volume = base
             x structural product trend
             x country demand driver (from the indicator panel)
             x seasonal profile
             x dated market event
             x account lifecycle (ramp / churn / contract step)
             x lognormal noise

    price  = list price
             x structural price trend
             x country price level
             x segment discount
             x dated pricing event
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Config
from . import reference as ref
from .indicators import build_market_indicators

# Average monthly revenue in EUR contributed by a size-1.0 account in a
# demand-1.0 market at the start of the observation window. These weights set
# the relative shape of the portfolio; absolute scale is calibrated afterwards
# to the configured base-year revenue target.
PRODUCT_REVENUE_WEIGHT: dict[str, float] = {
    "P01": 145_000.0,   # International Voice Termination
    "P02": 88_000.0,    # A2P Messaging
    "P03": 42_000.0,    # IPX Roaming & Signalling
    "P04": 26_000.0,    # IP Transit
    "P05": 58_000.0,    # Ethernet & Capacity
    "P06": 14_000.0,    # Cloud Connect
    "P07": 9_000.0,     # Voice Firewall & Anti-Fraud
}

CONTRACT_TYPES = ("Committed Volume", "Framework Agreement", "Spot / Pay-as-you-go")
CONTRACT_WEIGHTS = (0.38, 0.44, 0.18)


@dataclass
class Dataset:
    """Container for the generated star-schema tables."""
    dim_date: pd.DataFrame
    dim_country: pd.DataFrame
    dim_product: pd.DataFrame
    dim_customer: pd.DataFrame
    fact_traffic: pd.DataFrame
    fact_market_indicator: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "dim_date": self.dim_date,
            "dim_country": self.dim_country,
            "dim_product": self.dim_product,
            "dim_customer": self.dim_customer,
            "fact_traffic": self.fact_traffic,
            "fact_market_indicator": self.fact_market_indicator,
        }


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
def build_dim_date(months: pd.PeriodIndex) -> pd.DataFrame:
    ts = months.to_timestamp()
    return pd.DataFrame({
        "year_month": months.astype(str),
        "date": ts,
        "year": months.year,
        "quarter": [f"{p.year}-Q{p.quarter}" for p in months],
        "quarter_no": months.quarter,
        "month_no": months.month,
        "month_name": ts.strftime("%b"),
        "month_label": ts.strftime("%b %Y"),
        "days_in_month": ts.days_in_month,
        "half_year": [f"{p.year}-H{1 if p.month <= 6 else 2}" for p in months],
        "is_covid_period": [(pd.Period("2020-03", "M") <= p <= pd.Period("2021-06", "M"))
                            for p in months],
    })


def build_dim_customer(cfg: Config, rng: np.random.Generator) -> pd.DataFrame:
    """Create the anonymised customer base with lifecycle attributes."""
    n = int(cfg.generation["n_customers"])
    markets = ref.markets_frame()
    segments = ref.segments_frame()

    market_p = markets["demand_index"].to_numpy() / markets["demand_index"].sum()
    seg_p = segments["weight"].to_numpy() / segments["weight"].sum()

    country_codes = rng.choice(markets["country_code"].to_numpy(), size=n, p=market_p)
    seg_names = rng.choice(segments["segment"].to_numpy(), size=n, p=seg_p)

    hist_start, hist_end = cfg.history_start, cfg.history_end
    n_months = len(cfg.history_months)

    new_share = float(cfg.generation["new_business_share"])
    churn_share = float(cfg.generation["churn_share"])
    is_new = rng.random(n) < new_share
    is_churn = rng.random(n) < churn_share

    records = []
    per_country_seq: dict[str, int] = {}
    for i in range(n):
        cc = str(country_codes[i])
        seg_name = str(seg_names[i])
        seg = ref.SEGMENT_BY_NAME[seg_name]
        per_country_seq[cc] = per_country_seq.get(cc, 0) + 1

        size = float(rng.gamma(seg.size_shape, seg.size_scale))
        size = float(np.clip(size, 0.12, 14.0))

        # Accounts won inside the observation window ramp up from zero.
        if is_new[i]:
            start_offset = int(rng.integers(6, max(7, n_months - 14)))
            relationship_start = hist_start + start_offset
        else:
            relationship_start = hist_start - int(rng.integers(6, 96))

        # Churned accounts wind down before the end of the window.
        churn_month = None
        if is_churn[i] and not is_new[i]:
            churn_offset = int(rng.integers(18, n_months - 4))
            churn_month = hist_start + churn_offset

        products = list(seg.products)
        k = int(rng.integers(1, len(products) + 1))
        chosen = sorted(rng.choice(products, size=k, replace=False).tolist())

        records.append({
            "customer_id": f"CUS{i + 1:04d}",
            "customer_name": f"{seg_name} {cc}-{per_country_seq[cc]:02d}",
            "country_code": cc,
            "segment": seg_name,
            "contract_type": str(rng.choice(CONTRACT_TYPES, p=CONTRACT_WEIGHTS)),
            "account_size_factor": round(size, 4),
            "relationship_start": str(relationship_start),
            "churn_month": str(churn_month) if churn_month is not None else "",
            "status": "Churned" if churn_month is not None else "Active",
            "is_new_business": bool(is_new[i]),
            "products": ",".join(chosen),
        })

    df = pd.DataFrame(records)
    df["customer_tier"] = pd.cut(
        df["account_size_factor"],
        bins=[-np.inf, 1.0, 3.0, np.inf],
        labels=["Small", "Mid", "Key Account"],
    ).astype(str)
    _ = hist_end  # window end retained for readability of the lifecycle logic
    return df


# ---------------------------------------------------------------------------
# Driver construction
# ---------------------------------------------------------------------------
def _country_demand_drivers(indicators: pd.DataFrame,
                            months: pd.PeriodIndex) -> dict[tuple[str, str], np.ndarray]:
    """Map indicator series onto a demand multiplier per (country, product).

    Each product family is tied to the indicator that actually drives it, so
    the relationship the forecasting models later learn is a real one.
    """
    drivers: dict[tuple[str, str], np.ndarray] = {}
    month_str = months.astype(str)

    for cc, grp in indicators.groupby("country_code", sort=False):
        g = grp.set_index("year_month").reindex(month_str)
        traffic = (g["data_traffic_index"] / g["data_traffic_index"].iloc[0]).to_numpy()
        ott = (g["ott_substitution_index"] / g["ott_substitution_index"].iloc[0]).to_numpy()
        travel = (g["travel_index"] / g["travel_index"].iloc[0]).to_numpy()
        ecom = (g["ecommerce_index"] / g["ecommerce_index"].iloc[0]).to_numpy()

        # Voice: eroded by OTT substitution (elasticity ~0.55).
        drivers[(cc, "P01")] = ott ** -0.35
        # A2P messaging: pulled by online retail activity.
        drivers[(cc, "P02")] = ecom ** 0.45
        # Roaming: almost entirely a function of international travel.
        drivers[(cc, "P03")] = travel ** 0.93
        # Capacity products: scale with total data traffic, damped by the fact
        # that a wholesaler captures only part of market growth.
        drivers[(cc, "P04")] = traffic ** 0.22
        drivers[(cc, "P05")] = traffic ** 0.18
        drivers[(cc, "P06")] = traffic ** 0.24
        # Security: grows with overall traffic and fraud exposure.
        drivers[(cc, "P07")] = traffic ** 0.20
    return drivers


def _event_multipliers(months: pd.PeriodIndex) -> dict[str, dict[str, np.ndarray]]:
    """Dated volume / price / margin event multipliers per product."""
    n = len(months)
    ordinals = np.array([p.ordinal for p in months])

    def after(period: str) -> np.ndarray:
        return (ordinals >= pd.Period(period, "M").ordinal).astype(float)

    def ramp(start: str, end: str) -> np.ndarray:
        s, e = pd.Period(start, "M").ordinal, pd.Period(end, "M").ordinal
        return np.clip((ordinals - s) / max(e - s, 1), 0.0, 1.0)

    ones = np.ones(n)
    vol: dict[str, np.ndarray] = {p.product_id: ones.copy() for p in ref.PRODUCTS}
    price: dict[str, np.ndarray] = {p.product_id: ones.copy() for p in ref.PRODUCTS}
    margin: dict[str, np.ndarray] = {p.product_id: np.zeros(n) for p in ref.PRODUCTS}

    # EV01 - short 'call home' spike on international voice in spring 2020.
    call_home = np.zeros(n)
    for m, bump in (("2020-03", 0.06), ("2020-04", 0.14), ("2020-05", 0.11), ("2020-06", 0.05)):
        call_home += bump * (ordinals == pd.Period(m, "M").ordinal)
    vol["P01"] *= 1 + call_home

    # EV02 - permanent remote-work capacity step from April 2020.
    for pid in ("P04", "P05", "P06"):
        vol[pid] *= 1 + 0.09 * after("2020-04")

    # EV05 - regulated intra-EU termination rate cut, January 2023.
    price["P01"] *= 1 - 0.115 * after("2023-01")

    # EV07 - A2P price repair: aggregators pass through higher termination fees.
    price["P02"] *= 1 + 0.19 * ramp("2022-01", "2024-06")

    # EV06 - AI / data-centre driven traffic surge from mid-2024.
    for pid, uplift in (("P04", 0.21), ("P06", 0.16)):
        vol[pid] *= 1 + uplift * ramp("2024-06", "2026-06")

    # EV04 - energy and inflation shock compresses capacity gross margin.
    energy = np.clip(ramp("2022-06", "2022-12") - ramp("2023-06", "2024-06"), 0.0, 1.0)
    for pid in ("P04", "P05", "P06"):
        margin[pid] -= 0.048 * energy

    return {"volume": vol, "price": price, "margin": margin}


def _lifecycle_factor(months: pd.PeriodIndex, row: pd.Series,
                      rng: np.random.Generator) -> np.ndarray:
    """Account ramp-up, churn wind-down and mid-contract volume steps."""
    n = len(months)
    ordinals = np.array([p.ordinal for p in months])
    factor = np.ones(n)

    start = pd.Period(row["relationship_start"], "M").ordinal
    if start > ordinals[0]:
        # Six-month commercial ramp after go-live.
        elapsed = (ordinals - start) / 6.0
        factor *= np.clip(elapsed, 0.0, 1.0)

    if row["churn_month"]:
        churn = pd.Period(row["churn_month"], "M").ordinal
        # Three-month wind-down as traffic is re-routed to the winning carrier.
        remaining = 1.0 - np.clip((ordinals - churn) / 3.0 + 1e-9, 0.0, 1.0)
        factor *= np.where(ordinals >= churn, remaining, 1.0)

    # Roughly one account in four sees a step change when a route or a
    # framework agreement is renegotiated.
    if rng.random() < 0.25:
        step_at = int(rng.integers(12, n - 6))
        step = float(rng.uniform(-0.35, 0.45))
        factor *= 1 + step * (np.arange(n) >= step_at)

    return factor


def _scripted_events(customers: pd.DataFrame, months: pd.PeriodIndex
                     ) -> dict[tuple[str, str], np.ndarray]:
    """Two named commercial events, so the analysis has findable stories.

    Both are deliberate: a large Dutch carrier partially in-sources its voice
    traffic, and a Polish messaging aggregator wins a major retail programme.
    The reporting and AI layers should surface both without being told.
    """
    n = len(months)
    ordinals = np.array([p.ordinal for p in months])
    out: dict[tuple[str, str], np.ndarray] = {}

    nl = customers[(customers.country_code == "NL")
                   & (customers.segment == "Tier-1 Carrier")
                   & (customers["products"].str.contains("P01"))]
    if not nl.empty:
        cid = nl.sort_values("account_size_factor", ascending=False).iloc[0]["customer_id"]
        loss = pd.Period("2026-01", "M").ordinal
        out[(cid, "P01")] = 1 - 0.46 * np.clip((ordinals - loss) / 2.0 + 1e-9, 0.0, 1.0)

    pl = customers[(customers.country_code == "PL")
                   & (customers.segment == "Messaging Aggregator")]
    if not pl.empty:
        cid = pl.sort_values("account_size_factor", ascending=False).iloc[0]["customer_id"]
        win = pd.Period("2025-07", "M").ordinal
        out[(cid, "P02")] = 1 + 0.72 * np.clip((ordinals - win) / 3.0 + 1e-9, 0.0, 1.0)

    _ = n
    return out


# ---------------------------------------------------------------------------
# Fact generation
# ---------------------------------------------------------------------------
def build_fact_traffic(cfg: Config, customers: pd.DataFrame,
                       indicators: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    months = cfg.history_months
    n = len(months)
    month_str = months.astype(str).to_numpy()
    month_of_year = np.array([p.month for p in months])
    years_elapsed = np.arange(n) / 12.0

    drivers = _country_demand_drivers(indicators, months)
    events = _event_multipliers(months)
    scripted = _scripted_events(customers, months)
    sigma = float(cfg.generation["noise_sigma"])

    blocks: list[pd.DataFrame] = []
    for _, cust in customers.iterrows():
        cc = cust["country_code"]
        market = ref.MARKET_BY_CODE[cc]
        segment = ref.SEGMENT_BY_NAME[cust["segment"]]
        lifecycle = _lifecycle_factor(months, cust, rng)

        for pid in str(cust["products"]).split(","):
            product = ref.PRODUCT_BY_ID[pid]
            season = np.array(ref.SEASONAL_PROFILES[product.seasonality])[month_of_year - 1]

            # ---- volume -------------------------------------------------
            base_revenue = (PRODUCT_REVENUE_WEIGHT[pid]
                            * cust["account_size_factor"]
                            * (0.35 + 0.65 * market.demand_index))
            base_volume = base_revenue / product.base_unit_price_eur

            trend = (1 + product.volume_cagr) ** years_elapsed
            noise = np.exp(rng.normal(0.0, sigma, n))
            volume = (base_volume * trend * drivers[(cc, pid)] * season
                      * events["volume"][pid] * lifecycle * noise)
            if (cust["customer_id"], pid) in scripted:
                volume = volume * scripted[(cust["customer_id"], pid)]

            # ---- realised unit price ------------------------------------
            price = (product.base_unit_price_eur
                     * (1 + product.price_cagr) ** years_elapsed
                     * market.price_level_index
                     * (1 - segment.price_sensitivity)
                     * events["price"][pid]
                     * np.exp(rng.normal(0.0, sigma / 3.0, n)))

            revenue = volume * price
            gross_margin_pct = np.clip(
                product.base_margin + product.margin_drift_pa * years_elapsed
                + events["margin"][pid] + rng.normal(0.0, 0.006, n),
                0.02, 0.75,
            )
            cost = revenue * (1 - gross_margin_pct)

            blocks.append(pd.DataFrame({
                "year_month": month_str,
                "customer_id": cust["customer_id"],
                "country_code": cc,
                "product_id": pid,
                "volume_units": volume,
                "unit_price_eur": price,
                "revenue_eur": revenue,
                "cost_eur": cost,
            }))

    fact = pd.concat(blocks, ignore_index=True)

    # Drop the zero rows created before go-live / after churn completion.
    fact = fact[fact["revenue_eur"] > 1.0].copy()

    # ---- calibrate absolute scale to the configured base-year target ----
    target = float(cfg.generation.get("target_base_year_revenue_eur", 0) or 0)
    if target > 0:
        base_year = int(cfg.history_start.year)
        actual = fact.loc[fact["year_month"].str.startswith(str(base_year)), "revenue_eur"].sum()
        if actual > 0:
            scale = target / actual
            for col in ("volume_units", "revenue_eur", "cost_eur"):
                fact[col] *= scale

    fact["margin_eur"] = fact["revenue_eur"] - fact["cost_eur"]
    fact["margin_pct"] = fact["margin_eur"] / fact["revenue_eur"]
    fact = fact.round({
        "volume_units": 2, "unit_price_eur": 6, "revenue_eur": 2,
        "cost_eur": 2, "margin_eur": 2, "margin_pct": 4,
    })
    return fact.sort_values(["year_month", "country_code", "product_id", "customer_id"]
                            ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def generate_dataset(cfg: Config) -> Dataset:
    rng = np.random.default_rng(cfg.seed)
    months = cfg.history_months

    # dim_date spans history AND the forecast horizon: fact_forecast rows land
    # on months that are never in the raw fact table, and the Power BI /
    # Excel date table has to resolve them too.
    full_calendar = pd.period_range(months[0], periods=len(months) + cfg.horizon, freq="M")
    dim_date = build_dim_date(full_calendar)
    dim_country = ref.markets_frame()
    dim_product = ref.products_frame()
    dim_customer = build_dim_customer(cfg, rng)
    indicators = build_market_indicators(months, cfg.seed + 1)
    fact_traffic = build_fact_traffic(cfg, dim_customer, indicators, rng)

    return Dataset(
        dim_date=dim_date,
        dim_country=dim_country,
        dim_product=dim_product,
        dim_customer=dim_customer,
        fact_traffic=fact_traffic,
        fact_market_indicator=indicators,
    )


def write_dataset(cfg: Config, dataset: Dataset) -> dict[str, str]:
    """Persist the raw tables as CSV (the hand-off format for Excel/Power BI)."""
    out = cfg.path("raw")
    written: dict[str, str] = {}
    for name, frame in dataset.tables().items():
        path = out / f"{name}.csv"
        frame.to_csv(path, index=False)
        written[name] = str(path.relative_to(cfg.root))
    return written
