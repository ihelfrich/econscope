"""Revenue mix and per-member economic decomposition.

When you look at Soho House revenue going from $575M (2018) to $1.2B (2024),
the headline number hides the fact that the mix shifted. Membership dues went
from 23% to 35% of revenue. In-house spending per member peaked in 2022 and has
been falling since. That mix shift is the actual strategic story.

This module provides reusable methods for:

- `revenue_mix_shift`: how the share of each revenue line has evolved
- `arpu_decomposition`: average revenue per member by category, year over year
- `growth_decomposition`: separating volume from price/mix in headline growth
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ARPUResult:
    """Average-revenue-per-member analysis across years."""
    years: list[int]
    members: list[int]
    revenues: dict[str, list[float]]  # category -> [revenue per year]
    arpu: dict[str, list[float]]      # category -> [arpu per year]
    peak_year: dict[str, int] = field(default_factory=dict)  # category -> year of peak ARPU
    decline_from_peak_pct: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"ARPU decomposition over {len(self.years)} years\n"]
        lines.append(f"{'Year':<6} {'Members':>10}  " + "  ".join(f"{c[:14]:>14}" for c in self.arpu))
        lines.append("-" * (16 + 16 * len(self.arpu)))
        for i, y in enumerate(self.years):
            arpu_str = "  ".join(f"{self.arpu[c][i]:>14,.0f}" for c in self.arpu)
            lines.append(f"{y:<6} {self.members[i]:>10,}  {arpu_str}")
        if self.peak_year:
            lines.append("")
            for cat, peak_y in self.peak_year.items():
                decl = self.decline_from_peak_pct.get(cat, 0)
                lines.append(f"  {cat}: peaked in {peak_y}; current is {decl:+.1f}% from peak")
        return "\n".join(lines)


def revenue_mix_shift(
    *,
    years: list[int],
    revenues_by_category: dict[str, list[float]],
) -> dict[str, list[float]]:
    """Convert raw revenues by category into share-of-total each year.

    Parameters
    ----------
    years : list of int
    revenues_by_category : dict
        Mapping category name -> list of revenues for each year.

    Returns
    -------
    dict mapping category -> list of share-of-total each year (0-1).
    """
    n = len(years)
    totals = [0.0] * n
    for cat, vals in revenues_by_category.items():
        if len(vals) != n:
            raise ValueError(f"Category '{cat}' has {len(vals)} values, expected {n}")
        for i, v in enumerate(vals):
            totals[i] += v

    return {
        cat: [(vals[i] / totals[i] if totals[i] else 0.0) for i in range(n)]
        for cat, vals in revenues_by_category.items()
    }


def arpu_decomposition(
    *,
    years: list[int],
    members: list[int],
    revenues_by_category: dict[str, list[float]],
) -> ARPUResult:
    """Compute average revenue per member by category, year over year, and
    identify per-category peak years and current decline from peak.
    """
    if len(members) != len(years):
        raise ValueError("members list must match years list length")

    arpu: dict[str, list[float]] = {}
    peak_year: dict[str, int] = {}
    decline_from_peak: dict[str, float] = {}

    for cat, vals in revenues_by_category.items():
        if len(vals) != len(years):
            raise ValueError(f"Category '{cat}' has wrong length")
        cat_arpu = [(vals[i] / members[i] if members[i] else 0.0) for i in range(len(years))]
        arpu[cat] = cat_arpu
        max_idx = cat_arpu.index(max(cat_arpu))
        peak_year[cat] = years[max_idx]
        latest = cat_arpu[-1]
        peak = cat_arpu[max_idx]
        decline_from_peak[cat] = ((latest - peak) / peak * 100) if peak else 0.0

    return ARPUResult(
        years=years,
        members=members,
        revenues=revenues_by_category,
        arpu=arpu,
        peak_year=peak_year,
        decline_from_peak_pct=decline_from_peak,
    )


def growth_decomposition(
    *,
    revenue_t: float, revenue_p: float,
    units_t: int, units_p: int,
) -> dict[str, float]:
    """Decompose revenue growth into volume effect and price/mix effect.

    Total growth = volume effect + price/mix effect

    Volume effect = (units_t - units_p) * avg_price_p
    Price/mix effect = units_t * (avg_price_t - avg_price_p)

    Returns a dict with all three components plus the cross-check identity.
    """
    if units_p == 0 or units_t == 0:
        return {"error": "zero-unit period"}

    avg_p = revenue_p / units_p
    avg_t = revenue_t / units_t

    volume = (units_t - units_p) * avg_p
    price_mix = units_t * (avg_t - avg_p)
    total = revenue_t - revenue_p

    return {
        "total_growth": total,
        "volume_effect": volume,
        "price_mix_effect": price_mix,
        "volume_share": (volume / total) if total else 0.0,
        "price_mix_share": (price_mix / total) if total else 0.0,
        "avg_price_p": avg_p,
        "avg_price_t": avg_t,
        "units_p": units_p,
        "units_t": units_t,
    }
