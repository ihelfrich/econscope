"""Smoke tests for the intel and analyze modules.

These tests verify that the public API of each module is wired correctly and
that the core algorithms produce sensible outputs on synthetic data. They do
NOT hit live APIs (no network calls) — for that, see test_intel_integration.py.

Run with:
    cd ~/Projects/econscope && PYTHONPATH=. python3 -m pytest tests/test_intel_smoke.py -v
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest


# ── intel.http ────────────────────────────────────────────────────────────────

def test_http_cache_key_stable():
    from econscope.intel.http import _cache_key
    k1 = _cache_key("https://example.com/a", {"X": "1", "Y": "2"})
    k2 = _cache_key("https://example.com/a", {"Y": "2", "X": "1"})
    assert k1 == k2, "Cache key must be deterministic regardless of header order"


def test_http_cache_size_runs():
    from econscope.intel.http import cache_size
    info = cache_size()
    assert "entries" in info and "bytes" in info and "path" in info


# ── intel.network ─────────────────────────────────────────────────────────────

def test_network_graph_roundtrip():
    from econscope.intel.network import NetworkGraph, Node, Edge
    g = NetworkGraph(seed="Foo")
    g.nodes.append(Node(id="Foo", kind="seed", label="Foo"))
    g.nodes.append(Node(id="Bar", kind="sec_entity", label="Bar Inc."))
    g.edges.append(Edge(source="Foo", target="Bar", weight=3.0, kinds=["sec_co_mention"]))

    j = g.to_json()
    g2 = NetworkGraph.from_json(j)
    assert g2.seed == g.seed
    assert len(g2.nodes) == 2
    assert len(g2.edges) == 1
    assert g2.edges[0].weight == 3.0


def test_network_graph_top_by_weight():
    from econscope.intel.network import NetworkGraph, Edge
    g = NetworkGraph(seed="X")
    g.edges = [
        Edge("X", "A", 1.0, ["k"]),
        Edge("X", "B", 5.0, ["k"]),
        Edge("X", "C", 3.0, ["k"]),
    ]
    top = g.top_by_weight(2)
    assert [e.target for e in top] == ["B", "C"]


def test_network_normalize_strips_cik():
    from econscope.intel.network import _normalize_company_name
    assert _normalize_company_name("Soho House & Co Inc.  (SHCO)  (CIK 0001846510)") == "Soho House & Co Inc."
    assert _normalize_company_name("Apple Inc. (AAPL)") == "Apple Inc."


# ── intel.forensic ────────────────────────────────────────────────────────────

def test_altman_z_distress():
    """A company with negative working capital and operating loss should be in distress."""
    from econscope.intel.forensic import altman_z_score
    inputs = {
        "total_assets": 1000,
        "current_assets": 100,
        "current_liabilities": 500,
        "retained_earnings": -500,
        "operating_income": -50,
        "net_income": -100,
        "total_liabilities": 1100,
        "revenue": 800,
        "stockholders_equity": -100,
    }
    z = altman_z_score(inputs)
    assert z is not None
    assert z < 1.81, f"Expected distress (Z<1.81), got {z}"


def test_altman_z_safe():
    """A healthy company should be in the safe zone."""
    from econscope.intel.forensic import altman_z_score
    inputs = {
        "total_assets": 1000,
        "current_assets": 600,
        "current_liabilities": 200,
        "retained_earnings": 400,
        "operating_income": 200,
        "net_income": 150,
        "total_liabilities": 300,
        "revenue": 1200,
        "stockholders_equity": 700,
    }
    z = altman_z_score(inputs, market_value_equity=2000)
    assert z is not None
    assert z > 2.99, f"Expected safe (Z>2.99), got {z}"


def test_sloan_accruals():
    from econscope.intel.forensic import sloan_accruals
    inputs = {"net_income": 100, "cash_from_ops": 50, "total_assets": 1000}
    s = sloan_accruals(inputs)
    assert s is not None
    assert abs(s - 0.05) < 1e-9


def test_sloan_handles_missing():
    from econscope.intel.forensic import sloan_accruals
    assert sloan_accruals({"net_income": 100, "cash_from_ops": 50}) is None


def test_piotroski_strong_company():
    """A company that improved on every dimension should score 9."""
    from econscope.intel.forensic import piotroski_f_score
    curr = {
        "total_assets": 1100, "net_income": 150, "cash_from_ops": 200,
        "revenue": 1300, "long_term_debt": 100, "current_assets": 500,
        "current_liabilities": 200, "cost_of_goods": 700,
        "stockholders_equity": 600,
    }
    prev = {
        "total_assets": 1000, "net_income": 100, "cash_from_ops": 120,
        "revenue": 1100, "long_term_debt": 150, "current_assets": 400,
        "current_liabilities": 250, "cost_of_goods": 650,
        "stockholders_equity": 580,
    }
    score = piotroski_f_score(curr, prev)
    assert score is not None
    assert score >= 8, f"Expected strong score, got {score}"


def test_piotroski_no_prior_year():
    """With prev=None, max possible is 3 (only F1, F2, F4 testable)."""
    from econscope.intel.forensic import piotroski_f_score
    curr = {"net_income": 100, "cash_from_ops": 200, "total_assets": 1000}
    score = piotroski_f_score(curr, prev=None)
    assert score is not None
    assert 0 <= score <= 3


def test_going_concern_detection():
    from econscope.intel.forensic import going_concern_score
    text = "There is substantial doubt about our ability to continue as a going concern."
    r = going_concern_score(text)
    assert r["flagged"] is True
    assert r["phrase_count"] >= 1


def test_going_concern_clean():
    from econscope.intel.forensic import going_concern_score
    text = "The company expects to continue normal operations through next year."
    r = going_concern_score(text)
    assert r["flagged"] is False


# ── textdiff ──────────────────────────────────────────────────────────────────

def test_jaccard_identical():
    from econscope.intel.textdiff import jaccard_similarity
    t = "the quick brown fox jumps over the lazy dog and rests"
    assert jaccard_similarity(t, t) == 1.0


def test_jaccard_completely_different():
    from econscope.intel.textdiff import jaccard_similarity
    a = "alpha beta gamma delta epsilon zeta eta theta"
    b = "lambda mu nu xi omicron pi rho sigma"
    assert jaccard_similarity(a, b) == 0.0


def test_jaccard_partial_overlap():
    from econscope.intel.textdiff import jaccard_similarity
    a = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    b = "alpha beta gamma delta epsilon mu nu xi omicron pi"
    sim = jaccard_similarity(a, b)
    assert 0 < sim < 1, f"Expected partial overlap, got {sim}"


# ── analyze.monte_carlo ───────────────────────────────────────────────────────

def test_refinancing_simulation_reproducible():
    from econscope.analyze.monte_carlo import refinancing_simulation
    r1 = refinancing_simulation(
        debt_amount=1000, base_operating_income=100,
        rate_range=(0.05, 0.10), oi_std=20, n_draws=500, seed=42,
    )
    r2 = refinancing_simulation(
        debt_amount=1000, base_operating_income=100,
        rate_range=(0.05, 0.10), oi_std=20, n_draws=500, seed=42,
    )
    assert r1.distress_probability == r2.distress_probability


def test_refinancing_high_debt_high_distress():
    from econscope.analyze.monte_carlo import refinancing_simulation
    high = refinancing_simulation(
        debt_amount=10_000, base_operating_income=100,
        rate_range=(0.05, 0.10), oi_std=20, n_draws=2000, seed=42,
    )
    low = refinancing_simulation(
        debt_amount=100, base_operating_income=100,
        rate_range=(0.05, 0.10), oi_std=20, n_draws=2000, seed=42,
    )
    assert high.distress_probability > low.distress_probability


# ── analyze.decomposition ─────────────────────────────────────────────────────

def test_revenue_mix_shift_sums_to_one():
    from econscope.analyze.decomposition import revenue_mix_shift
    shares = revenue_mix_shift(
        years=[2020, 2021],
        revenues_by_category={"dues": [100.0, 200.0], "in_house": [300.0, 200.0]},
    )
    for i in range(2):
        total = sum(shares[c][i] for c in shares)
        assert abs(total - 1.0) < 1e-9


def test_arpu_decomposition_finds_peak():
    from econscope.analyze.decomposition import arpu_decomposition
    result = arpu_decomposition(
        years=[2020, 2021, 2022, 2023],
        members=[100, 110, 120, 130],
        revenues_by_category={
            "in_house": [1000, 1500, 2000, 1800],  # peaks in 2022
        },
    )
    assert result.peak_year["in_house"] == 2022
    assert result.decline_from_peak_pct["in_house"] < 0


# ── analyze.elasticity ────────────────────────────────────────────────────────

def test_elasticity_warns_on_supply_shift():
    from econscope.analyze.elasticity import pricing_power_ratio
    r = pricing_power_ratio(
        year_p=2020, year_t=2024,
        price_p=100, price_t=130,
        quantity_p=1000, quantity_t=1500,
        supply_changed=True,
        supply_change_description="Opened 5 new locations",
    )
    assert not r.is_elasticity
    assert any(w.kind == "supply_shifting" for w in r.warnings)


def test_elasticity_clean_no_warnings():
    from econscope.analyze.elasticity import pricing_power_ratio
    r = pricing_power_ratio(
        year_p=2020, year_t=2024,
        price_p=100, price_t=130,
        quantity_p=1000, quantity_t=900,
    )
    assert r.is_elasticity  # no warnings


# ── report ────────────────────────────────────────────────────────────────────

def test_palette_complete():
    from econscope.report.charts import PALETTE
    for key in ["primary", "accent_red", "accent_gold", "accent_green",
                "gray", "dark", "off_white"]:
        assert key in PALETTE
        assert PALETTE[key].startswith("#")


def test_render_network_runs(tmp_path):
    """Render a synthetic graph end-to-end."""
    from econscope.intel.network import NetworkGraph, Node, Edge
    from econscope.report.network_viz import render_network

    g = NetworkGraph(seed="Test")
    g.nodes = [
        Node(id="Test", kind="seed", label="Test"),
        Node(id="A", kind="sec_entity", label="Company A"),
        Node(id="B", kind="holder", label="Holder B"),
    ]
    g.edges = [
        Edge("Test", "A", 5.0, ["sec_co_mention"]),
        Edge("Test", "B", 3.0, ["ownership_filer"]),
    ]

    out = tmp_path / "test.png"
    result = render_network(g, output=str(out))
    assert Path(result).exists()
    assert Path(result).stat().st_size > 1000  # not an empty file
