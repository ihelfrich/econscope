"""Monte Carlo simulation for refinancing and distress analysis.

The Soho House refinancing analysis used a Monte Carlo over plausible
refinancing-rate and operating-income scenarios. This module generalizes that
into a reusable distress simulator.

The setup is intentionally conservative:

- Refinancing rate is drawn uniformly from a user-supplied range (representing
  the uncertainty about where rates will be at maturity).
- Operating income is drawn normally around a base scenario with user-supplied
  standard deviation (representing forecast uncertainty about the firm's run-rate).
- Interest coverage = operating income / (debt * refinancing rate). A coverage
  below 1.0x means the firm cannot make interest payments from operations.

The output includes the full distribution, summary statistics, and the
probability that coverage falls below configurable distress thresholds.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RefinancingResult:
    """Outcome of one refinancing Monte Carlo simulation."""
    n_draws: int
    debt_amount: float
    base_operating_income: float
    rate_range: tuple[float, float]
    oi_std: float
    coverage_samples: list[float] = field(default_factory=list)
    distress_threshold: float = 1.0
    distress_probability: float = 0.0
    mean_coverage: float = 0.0
    median_coverage: float = 0.0
    p10_coverage: float = 0.0
    p90_coverage: float = 0.0

    def summary(self) -> str:
        return (
            f"Refinancing simulation ({self.n_draws:,} draws)\n"
            f"  Debt: ${self.debt_amount:,.0f}\n"
            f"  Base operating income: ${self.base_operating_income:,.0f}\n"
            f"  Rate range: {self.rate_range[0]:.1%} to {self.rate_range[1]:.1%}\n"
            f"  OI std dev: ${self.oi_std:,.0f}\n"
            f"\n"
            f"  Distress probability (coverage < {self.distress_threshold:.1f}x): "
            f"{self.distress_probability:.1%}\n"
            f"  Mean coverage:   {self.mean_coverage:.2f}x\n"
            f"  Median coverage: {self.median_coverage:.2f}x\n"
            f"  10th-90th pct:   {self.p10_coverage:.2f}x to {self.p90_coverage:.2f}x"
        )


def refinancing_simulation(
    *,
    debt_amount: float,
    base_operating_income: float,
    rate_range: tuple[float, float],
    oi_std: float,
    n_draws: int = 10_000,
    distress_threshold: float = 1.0,
    seed: Optional[int] = 42,
) -> RefinancingResult:
    """Run a Monte Carlo simulation of debt-coverage outcomes at refinancing.

    Parameters
    ----------
    debt_amount : float
        Principal amount being refinanced (USD).
    base_operating_income : float
        Expected operating income at refinancing year (USD).
    rate_range : (float, float)
        Lower and upper bounds for the refinancing rate, as decimal (e.g. (0.06, 0.11)).
    oi_std : float
        Standard deviation of operating income forecast (USD).
    n_draws : int
        Number of random scenarios.
    distress_threshold : float
        Coverage ratio below which we consider the firm distressed (typically 1.0).
    seed : int, optional
        Random seed for reproducibility.

    Returns
    -------
    RefinancingResult
        Full distribution plus summary statistics.
    """
    if seed is not None:
        random.seed(seed)

    rate_low, rate_high = rate_range
    coverages: list[float] = []
    distress_count = 0

    for _ in range(n_draws):
        rate = random.uniform(rate_low, rate_high)
        oi = random.gauss(base_operating_income, oi_std)
        interest_expense = debt_amount * rate
        if interest_expense <= 0:
            coverage = float("inf")
        else:
            coverage = oi / interest_expense
        coverages.append(coverage)
        if coverage < distress_threshold:
            distress_count += 1

    coverages_sorted = sorted(coverages)
    n = len(coverages_sorted)

    return RefinancingResult(
        n_draws=n_draws,
        debt_amount=debt_amount,
        base_operating_income=base_operating_income,
        rate_range=rate_range,
        oi_std=oi_std,
        coverage_samples=coverages,
        distress_threshold=distress_threshold,
        distress_probability=distress_count / n_draws,
        mean_coverage=statistics.mean(coverages),
        median_coverage=statistics.median(coverages),
        p10_coverage=coverages_sorted[int(n * 0.1)],
        p90_coverage=coverages_sorted[int(n * 0.9)],
    )


def sensitivity_grid(
    *,
    debt_amount: float,
    base_operating_income: float,
    rate_values: list[float],
    oi_values: list[float],
    distress_threshold: float = 1.0,
) -> list[dict]:
    """Compute deterministic coverage across a grid of (rate, OI) pairs.

    Useful for the heatmap companion to a Monte Carlo: it shows the
    structural sensitivity, not the probabilistic one.

    Returns a list of dicts with keys: rate, operating_income, coverage, distressed.
    """
    out = []
    for rate in rate_values:
        for oi in oi_values:
            interest = debt_amount * rate
            coverage = oi / interest if interest > 0 else float("inf")
            out.append({
                "rate": rate,
                "operating_income": oi,
                "coverage": coverage,
                "distressed": coverage < distress_threshold,
            })
    return out
