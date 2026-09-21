"""Market indicator generation.

Produces a monthly panel of macro / market indicators per country. These are
not decoration: the demand model in :mod:`eu_wholesale.data.generate` derives
its country-level demand multipliers from these series, and the forecasting
feature set consumes them as leading indicators. Signal in the indicators is
therefore genuinely present in the traffic and revenue facts.

Indicator definitions
---------------------
gdp_growth_yoy         Real GDP growth, year on year (%).
cpi_yoy                Consumer price inflation, year on year (%).
data_traffic_index     Fixed + mobile data volume, index 100 = Jan 2019.
ott_substitution_index Share of communication migrated to OTT apps, index 100.
travel_index           International travel activity, index 100 = Jan 2019.
ecommerce_index        Online retail turnover, index 100 = Jan 2019.
mobile_penetration     SIM cards per capita.
price_pressure_index   Competitive price intensity, index 100 (higher = tougher).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .reference import MARKETS

INDICATORS: tuple[str, ...] = (
    "gdp_growth_yoy",
    "cpi_yoy",
    "data_traffic_index",
    "ott_substitution_index",
    "travel_index",
    "ecommerce_index",
    "mobile_penetration",
    "price_pressure_index",
)


def _interp_anchors(months: pd.PeriodIndex, anchors: dict[str, float]) -> np.ndarray:
    """Piecewise-linear interpolation between dated anchor points.

    Anchors are given as ``{"YYYY-MM": value}``. Values before the first and
    after the last anchor are held flat, which keeps every documented shock
    (COVID travel restrictions, the inflation spike) explicit and auditable
    rather than buried in random noise.
    """
    ordinals = np.array([p.ordinal for p in months], dtype=float)
    keys = sorted(anchors, key=lambda k: pd.Period(k, freq="M").ordinal)
    xs = np.array([pd.Period(k, freq="M").ordinal for k in keys], dtype=float)
    ys = np.array([anchors[k] for k in keys], dtype=float)
    return np.interp(ordinals, xs, ys)


def _ar1_noise(rng: np.random.Generator, n: int, sigma: float, phi: float = 0.72) -> np.ndarray:
    """Serially correlated noise - macro series do not jump around independently."""
    eps = rng.normal(0.0, sigma, n)
    out = np.empty(n)
    out[0] = eps[0]
    for i in range(1, n):
        out[i] = phi * out[i - 1] + eps[i]
    return out


def build_market_indicators(months: pd.PeriodIndex, seed: int) -> pd.DataFrame:
    """Build the monthly country x indicator panel."""
    rng = np.random.default_rng(seed)
    n = len(months)
    t = np.arange(n, dtype=float)
    years = t / 12.0
    month_of_year = np.array([p.month for p in months])

    # ---- shared European shock profiles ---------------------------------
    # International travel: near-total collapse in Q2 2020, staged recovery,
    # back above pre-pandemic levels from mid-2022 (EV01 / EV03).
    travel = _interp_anchors(months, {
        "2019-01": 100.0, "2020-01": 102.0, "2020-02": 96.0, "2020-03": 44.0,
        "2020-04": 9.0,   "2020-06": 14.0,  "2020-08": 38.0, "2020-10": 24.0,
        "2021-02": 17.0,  "2021-05": 31.0,  "2021-08": 62.0, "2021-11": 55.0,
        "2022-02": 71.0,  "2022-06": 96.0,  "2022-09": 104.0, "2023-06": 110.0,
        "2024-06": 116.0, "2025-06": 121.0, "2026-06": 125.0,
    })
    # Euro-area inflation: benign, 2022 energy spike (EV04), slow normalisation.
    cpi = _interp_anchors(months, {
        "2019-01": 1.6, "2020-05": 0.2, "2021-01": 1.1, "2021-11": 4.9,
        "2022-10": 10.6, "2023-06": 5.4, "2024-01": 2.9, "2025-01": 2.2,
        "2026-06": 2.1,
    })
    gdp = _interp_anchors(months, {
        "2019-01": 1.8, "2020-02": 0.9, "2020-05": -13.5, "2020-12": -4.2,
        "2021-06": 8.4, "2022-01": 4.6, "2022-12": 1.4, "2023-09": 0.2,
        "2024-06": 1.1, "2025-06": 1.5, "2026-06": 1.6,
    })

    rows: list[pd.DataFrame] = []
    for m in MARKETS:
        dev = 1.0 if m.market_maturity == "Developing" else 0.0

        # Data traffic compounds fastest in developing markets and steps up
        # permanently with remote work from Q2 2020 (EV02).
        traffic_cagr = 0.255 + 0.055 * dev
        remote_step = np.where(t >= (pd.Period("2020-04", "M").ordinal - months[0].ordinal), 0.11, 0.0)
        data_traffic = 100.0 * (1 + traffic_cagr) ** years * (1 + remote_step)
        data_traffic *= np.exp(_ar1_noise(rng, n, 0.012))

        # OTT substitution - the structural driver behind voice minute decline.
        ott = 100.0 * (1 + 0.082 + 0.02 * dev) ** years
        ott *= np.exp(_ar1_noise(rng, n, 0.008))

        # E-commerce - the demand driver behind A2P messaging volumes.
        ecom_base = 100.0 * (1 + 0.118) ** years
        ecom_covid = _interp_anchors(months, {
            "2019-01": 1.0, "2020-02": 1.0, "2020-05": 1.34, "2020-12": 1.28,
            "2021-08": 1.19, "2022-06": 1.10, "2023-06": 1.06, "2026-06": 1.04,
        })
        # Seasonal e-commerce peak around the November/December retail events.
        ecom_season = 1.0 + 0.16 * (month_of_year == 11) + 0.10 * (month_of_year == 12)
        ecommerce = ecom_base * ecom_covid * ecom_season * np.exp(_ar1_noise(rng, n, 0.014))

        penetration = m.mobile_penetration * (1 + 0.011) ** years + _ar1_noise(rng, n, 0.002)

        # Competitive intensity rises fastest where price levels are lowest.
        price_pressure = (100.0 * (1 + 0.031 + 0.014 * dev) ** years
                          * np.exp(_ar1_noise(rng, n, 0.010)))

        country_gdp = gdp + (0.6 * dev) + _ar1_noise(rng, n, 0.35)
        country_cpi = cpi * (1.0 + 0.22 * dev) + _ar1_noise(rng, n, 0.18)
        country_travel = travel * (1 + 0.04 * (m.region == "Southern EU")) \
            * np.exp(_ar1_noise(rng, n, 0.020))

        frame = pd.DataFrame({
            "year_month": months.astype(str),
            "country_code": m.country_code,
            "gdp_growth_yoy": country_gdp,
            "cpi_yoy": country_cpi,
            "data_traffic_index": data_traffic,
            "ott_substitution_index": ott,
            "travel_index": country_travel,
            "ecommerce_index": ecommerce,
            "mobile_penetration": penetration,
            "price_pressure_index": price_pressure,
        })
        rows.append(frame)

    out = pd.concat(rows, ignore_index=True)
    numeric = [c for c in out.columns if c not in ("year_month", "country_code")]
    out[numeric] = out[numeric].round(4)
    return out.sort_values(["country_code", "year_month"]).reset_index(drop=True)
