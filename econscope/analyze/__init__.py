"""Analyze module: quantitative methods that operate on data already pulled.

The `analyze` layer assumes the data exists (in the warehouse or as a passed-in
panel) and produces interpretable numerical results: distress probabilities,
revenue-mix decompositions, elasticity estimates with proper caveats, etc.

Each submodule answers a specific analytical question with a method that is
either textbook-standard (Monte Carlo simulation, growth-share decomposition)
or carefully scoped with documented caveats (elasticity estimation under
simultaneous supply changes).
"""

from econscope.analyze.monte_carlo import (
    refinancing_simulation,
    RefinancingResult,
)
from econscope.analyze.decomposition import (
    revenue_mix_shift,
    arpu_decomposition,
    growth_decomposition,
    ARPUResult,
)
from econscope.analyze.elasticity import (
    pricing_power_ratio,
    PricingPowerWarning,
)

__all__ = [
    "refinancing_simulation",
    "RefinancingResult",
    "revenue_mix_shift",
    "arpu_decomposition",
    "growth_decomposition",
    "ARPUResult",
    "pricing_power_ratio",
    "PricingPowerWarning",
]
