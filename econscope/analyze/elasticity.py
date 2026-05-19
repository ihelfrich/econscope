"""Pricing-power analysis (NOT elasticity, when supply is moving).

The Soho House analysis caught a real economic mistake: computing %dQ / %dP
across years where new houses were also opening, and calling the result an
"elasticity." It isn't. When supply is changing simultaneously with price, the
ratio is contaminated by supply-shift effects that move along the demand curve.

This module computes the ratio with explicit warnings about identification.
The caller gets the number AND a structured warning explaining what would need
to be true for the number to be interpretable as a clean elasticity.

If you want a real demand elasticity, you need either:
- An instrument for price (e.g., a tax change that moves price but not demand)
- A natural experiment (a market entry that moves quantity but not preferences)
- A panel with within-market price variation and fixed effects

None of which our Soho House data has. So we report the ratio honestly and
flag the identification issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PricingPowerWarning:
    """Structured caveat to attach to any pricing-power ratio."""
    kind: str  # "supply_shifting", "external_shock", "selection", "small_n"
    description: str


@dataclass
class PricingPowerResult:
    year_p: int
    year_t: int
    price_p: float
    price_t: float
    quantity_p: float
    quantity_t: float
    pct_change_price: float
    pct_change_quantity: float
    ratio: float
    warnings: list[PricingPowerWarning] = field(default_factory=list)

    @property
    def is_elasticity(self) -> bool:
        """True only if no identifying warnings are attached."""
        return len(self.warnings) == 0

    def summary(self) -> str:
        label = "Demand elasticity (clean)" if self.is_elasticity else "Pricing-power ratio (NOT an elasticity)"
        lines = [
            label,
            f"  {self.year_p} -> {self.year_t}",
            f"  Price:    {self.price_p:.2f} -> {self.price_t:.2f}  ({self.pct_change_price:+.1%})",
            f"  Quantity: {self.quantity_p:,.0f} -> {self.quantity_t:,.0f}  ({self.pct_change_quantity:+.1%})",
            f"  Ratio %dQ/%dP: {self.ratio:+.3f}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("  WARNINGS — this ratio is NOT a clean demand elasticity:")
            for w in self.warnings:
                lines.append(f"    [{w.kind}] {w.description}")
        return "\n".join(lines)


def pricing_power_ratio(
    *,
    year_p: int, year_t: int,
    price_p: float, price_t: float,
    quantity_p: float, quantity_t: float,
    supply_changed: bool = False,
    supply_change_description: str = "",
    external_shock: bool = False,
    external_shock_description: str = "",
    selection_concern: bool = False,
    selection_description: str = "",
) -> PricingPowerResult:
    """Compute %dQ/%dP between two periods with identification warnings.

    Parameters
    ----------
    year_p, year_t : int
        Prior and current years.
    price_p, price_t : float
        Prices in the two periods.
    quantity_p, quantity_t : float
        Quantities in the two periods.
    supply_changed : bool
        Did the supply side change between periods? (new locations, new
        capacity, new tiers). If True, this is NOT an elasticity.
    supply_change_description : str
        Free-text description of what changed on the supply side.
    external_shock : bool
        Did an unrelated external shock occur (COVID, recession, etc.)?
    external_shock_description : str
    selection_concern : bool
        Are the customers in period t a different selection than period p
        (e.g. waitlist policy changes, geographic expansion)?

    Returns
    -------
    PricingPowerResult
        Ratio plus all attached warnings. Caller should read `is_elasticity`
        to decide whether to interpret as a true demand elasticity.
    """
    if price_p <= 0 or quantity_p <= 0:
        raise ValueError("Prior-period price and quantity must be positive")

    pct_p = (price_t - price_p) / price_p
    pct_q = (quantity_t - quantity_p) / quantity_p
    ratio = pct_q / pct_p if pct_p != 0 else float("nan")

    warnings = []
    if supply_changed:
        warnings.append(PricingPowerWarning(
            "supply_shifting",
            supply_change_description or
            "Supply changed between periods — observed quantity reflects both demand response and supply shift. "
            "Cannot identify demand elasticity from %dQ/%dP alone.",
        ))
    if external_shock:
        warnings.append(PricingPowerWarning(
            "external_shock",
            external_shock_description or
            "External shock between periods confounds the price-quantity relationship.",
        ))
    if selection_concern:
        warnings.append(PricingPowerWarning(
            "selection",
            selection_description or
            "Customer selection differs between periods. Observed elasticity may reflect "
            "different customer types, not demand response of the same customers.",
        ))

    return PricingPowerResult(
        year_p=year_p, year_t=year_t,
        price_p=price_p, price_t=price_t,
        quantity_p=quantity_p, quantity_t=quantity_t,
        pct_change_price=pct_p,
        pct_change_quantity=pct_q,
        ratio=ratio,
        warnings=warnings,
    )
