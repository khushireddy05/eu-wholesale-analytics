"""Reference (master) data for the EU wholesale market model.

This module is the single source of truth for the business dimensions:
markets, the wholesale product portfolio and the structural drivers that shape
each product's demand curve. Keeping them here - rather than scattered through
the generator - means the domain assumptions are reviewable in one place.

All figures are illustrative and calibrated to publicly observable industry
dynamics (voice minutes in structural decline, A2P messaging monetising,
IP transit volume growth offset by unit-price deflation, roaming traffic
collapsing during COVID travel restrictions and recovering from 2022).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Market:
    country_code: str
    country_name: str
    region: str
    population_m: float
    gdp_per_capita_keur: float
    mobile_penetration: float      # SIMs per capita
    market_maturity: str           # Mature | Developing
    price_level_index: float       # 1.00 = EU average realised price
    demand_index: float            # relative size of the wholesale opportunity
    group_footprint: bool          # group has a national operating company


MARKETS: tuple[Market, ...] = (
    Market("DE", "Germany",        "Western EU",  84.4, 48.9, 1.33, "Mature",     1.06, 1.00, True),
    Market("FR", "France",         "Western EU",  68.1, 41.4, 1.21, "Mature",     0.97, 0.78, False),
    Market("NL", "Netherlands",    "Western EU",  17.9, 55.9, 1.25, "Mature",     1.02, 0.44, True),
    Market("AT", "Austria",        "Western EU",   9.2, 52.1, 1.42, "Mature",     1.04, 0.26, True),
    Market("PL", "Poland",         "Central EU",  36.7, 20.4, 1.38, "Developing", 0.82, 0.52, True),
    Market("CZ", "Czechia",        "Central EU",  10.9, 26.8, 1.31, "Mature",     0.88, 0.22, True),
    Market("SK", "Slovakia",       "Central EU",   5.4, 21.9, 1.35, "Mature",     0.86, 0.13, True),
    Market("HU", "Hungary",        "Central EU",   9.6, 18.4, 1.19, "Developing", 0.81, 0.15, True),
    Market("RO", "Romania",        "Central EU",  19.1, 15.9, 1.17, "Developing", 0.74, 0.24, True),
    Market("HR", "Croatia",        "Southern EU",  3.9, 18.1, 1.09, "Developing", 0.79, 0.09, True),
    Market("GR", "Greece",         "Southern EU", 10.4, 20.9, 1.16, "Developing", 0.83, 0.17, True),
    Market("IT", "Italy",          "Southern EU", 58.8, 34.8, 1.49, "Mature",     0.91, 0.71, False),
    Market("ES", "Spain",          "Southern EU", 48.3, 29.6, 1.24, "Mature",     0.89, 0.63, False),
)


# ---------------------------------------------------------------------------
# Wholesale product portfolio
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Product:
    product_id: str
    product_name: str
    product_family: str
    unit: str                 # billing unit for traffic volume
    lifecycle_stage: str      # Growth | Mature | Decline
    base_unit_price_eur: float
    # Structural annual rates (compounded monthly by the generator)
    volume_cagr: float        # underlying annual volume growth
    price_cagr: float         # annual change in realised unit price
    base_margin: float        # gross margin on revenue at series start
    margin_drift_pa: float    # annual absolute change in gross margin
    seasonality: str          # seasonal profile key (see SEASONAL_PROFILES)
    covid_sensitivity: float  # 0 = immune, 1 = fully exposed to travel shock


PRODUCTS: tuple[Product, ...] = (
    Product("P01", "International Voice Termination", "Voice",
            "minutes", "Decline", 0.01850, -0.090, -0.062, 0.121, -0.004, "voice", 0.15),
    Product("P02", "A2P Messaging", "Messaging",
            "sms", "Mature", 0.04100, 0.076, 0.043, 0.184, 0.006, "messaging", 0.05),
    Product("P03", "IPX Roaming & Signalling", "Mobile Data & Roaming",
            "gb", "Growth", 1.85000, 0.235, -0.118, 0.268, -0.003, "roaming", 0.95),
    Product("P04", "IP Transit", "Internet & Capacity",
            "mbps", "Growth", 0.42000, 0.281, -0.215, 0.312, -0.008, "capacity", 0.00),
    Product("P05", "Ethernet & Capacity Services", "Internet & Capacity",
            "mbps", "Mature", 1.10000, 0.062, -0.078, 0.348, -0.005, "capacity", 0.10),
    Product("P06", "Cloud Connect", "Internet & Capacity",
            "mbps", "Growth", 2.40000, 0.238, -0.096, 0.402, 0.004, "capacity", 0.00),
    Product("P07", "Voice Firewall & Anti-Fraud", "Security",
            "protected_subs_k", "Growth", 0.09000, 0.183, -0.028, 0.512, 0.007, "flat", 0.00),
)


# ---------------------------------------------------------------------------
# Customer segments
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Segment:
    segment: str
    weight: float             # share of the customer base
    size_shape: float         # gamma shape for account size (lower = more skew)
    size_scale: float         # gamma scale, drives average account size
    price_sensitivity: float  # discount vs. list price
    products: tuple[str, ...] # products this segment typically buys


SEGMENTS: tuple[Segment, ...] = (
    Segment("Tier-1 Carrier",       0.14, 3.2, 1.90, 0.145,
            ("P01", "P03", "P04", "P05", "P07")),
    Segment("Tier-2 Carrier",       0.26, 2.1, 0.95, 0.095,
            ("P01", "P03", "P05", "P07")),
    Segment("MVNO",                 0.16, 1.7, 0.55, 0.070,
            ("P01", "P03", "P07")),
    Segment("Messaging Aggregator", 0.15, 1.9, 0.85, 0.120,
            ("P02", "P07")),
    Segment("Hyperscaler & OTT",    0.09, 2.6, 1.75, 0.185,
            ("P04", "P06", "P05")),
    Segment("Enterprise Aggregator", 0.20, 1.5, 0.60, 0.060,
            ("P04", "P05", "P06", "P02")),
)


# ---------------------------------------------------------------------------
# Seasonal profiles - multiplicative factors by calendar month (Jan..Dec)
# ---------------------------------------------------------------------------
SEASONAL_PROFILES: dict[str, list[float]] = {
    # International voice: February short-month dip, December festive peak.
    "voice":     [0.98, 0.92, 1.01, 0.99, 1.00, 0.98, 1.02, 1.00, 1.00, 1.03, 1.02, 1.09],
    # A2P: e-commerce driven - Black Friday / Christmas surge, January hangover.
    "messaging": [0.88, 0.90, 0.97, 0.98, 1.01, 0.97, 0.95, 0.93, 1.02, 1.08, 1.22, 1.14],
    # Roaming: dominated by the European summer travel season.
    "roaming":   [0.74, 0.74, 0.83, 0.94, 1.03, 1.18, 1.46, 1.44, 1.09, 0.92, 0.80, 0.86],
    # Contracted capacity: near-flat, small December change-freeze effect.
    "capacity":  [1.00, 0.99, 1.01, 1.00, 1.00, 1.01, 0.99, 0.98, 1.01, 1.01, 1.01, 0.98],
    "flat":      [1.0] * 12,
}


# ---------------------------------------------------------------------------
# Structural events - documented, dated market shocks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    name: str
    start: str
    end: str
    description: str


MARKET_EVENTS: tuple[MarketEvent, ...] = (
    MarketEvent("EV01", "COVID-19 travel restrictions", "2020-03", "2021-06",
                "Roaming traffic collapses with international travel; international "
                "voice sees a short 'call home' spike; transit steps up on remote work."),
    MarketEvent("EV02", "Remote-work capacity step", "2020-04", "2026-06",
                "Permanent uplift in IP transit and cloud connect demand."),
    MarketEvent("EV03", "Travel recovery", "2022-03", "2023-09",
                "Roaming volumes recover above pre-pandemic levels."),
    MarketEvent("EV04", "Energy & inflation shock", "2022-06", "2023-12",
                "Network operating cost inflation compresses capacity margins."),
    MarketEvent("EV05", "Intra-EU voice rate regulation", "2023-01", "2026-06",
                "Regulated glide path caps intra-EU termination rates - step price cut."),
    MarketEvent("EV06", "AI / data-centre traffic surge", "2024-06", "2026-06",
                "Additional IP transit and cloud connect volume growth."),
    MarketEvent("EV07", "A2P price repair", "2022-01", "2026-06",
                "Operators raise A2P termination fees; realised price growth accelerates."),
)


# ---------------------------------------------------------------------------
# Frame builders
# ---------------------------------------------------------------------------
def markets_frame() -> pd.DataFrame:
    # Renamed on the way out: the monthly indicator panel also carries a
    # mobile_penetration series, and the two must not collide on join.
    return (pd.DataFrame([asdict(m) for m in MARKETS])
            .rename(columns={"mobile_penetration": "mobile_penetration_base"}))


def products_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(p) for p in PRODUCTS])


def segments_frame() -> pd.DataFrame:
    df = pd.DataFrame([asdict(s) for s in SEGMENTS])
    df["products"] = df["products"].apply(list)
    return df


def events_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(e) for e in MARKET_EVENTS])


PRODUCT_BY_ID: dict[str, Product] = {p.product_id: p for p in PRODUCTS}
MARKET_BY_CODE: dict[str, Market] = {m.country_code: m for m in MARKETS}
SEGMENT_BY_NAME: dict[str, Segment] = {s.segment: s for s in SEGMENTS}
