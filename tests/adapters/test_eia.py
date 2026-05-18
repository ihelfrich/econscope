"""Tests for the EIA adapter (requires EIA_API_KEY)."""

from __future__ import annotations

import os
import pytest
from econscope.adapters.eia import EIAAdapter, COMMON_ROUTES


@pytest.fixture
def eia():
    key = os.environ.get("EIA_API_KEY")
    if not key:
        pytest.skip("EIA_API_KEY not set")
    return EIAAdapter()


class TestEIASearch:
    def test_search_crude(self, eia):
        results = eia.search("crude")
        assert len(results) >= 1
        assert all(r.source == "eia" for r in results)

    def test_search_gas(self, eia):
        results = eia.search("gas")
        assert len(results) >= 1

    def test_search_electricity(self, eia):
        results = eia.search("electricity")
        assert len(results) >= 1

    def test_common_routes_populated(self):
        assert len(COMMON_ROUTES) >= 10
        assert "crude_wti" in COMMON_ROUTES
        assert "natgas_price" in COMMON_ROUTES


class TestEIAPull:
    def test_pull_crude_wti(self, eia):
        result = eia.pull_series("crude_wti", start="2024-01-01")
        assert result.ok
        assert result.count > 0
        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)
        assert obs["value"] > 0  # Oil prices should be positive

    def test_pull_observations_sorted(self, eia):
        result = eia.pull_series("crude_wti", start="2023-01-01")
        assert result.ok
        dates = [o["date"] for o in result.observations]
        assert dates == sorted(dates)

    def test_pull_raw_bytes(self, eia):
        result = eia.pull_series("crude_wti", start="2024-01-01")
        assert result.ok
        assert len(result.raw_bytes) > 0


class TestEIAHelpers:
    def test_parse_period_annual(self):
        assert EIAAdapter._parse_period("2024") == "2024-01-01"

    def test_parse_period_monthly(self):
        assert EIAAdapter._parse_period("2024-03") == "2024-03-01"

    def test_parse_period_daily(self):
        assert EIAAdapter._parse_period("2024-03-15") == "2024-03-15"

    def test_parse_period_empty(self):
        assert EIAAdapter._parse_period("") is None
        assert EIAAdapter._parse_period(None) is None


class TestEIAVerify:
    def test_verify_key(self, eia):
        ok, msg = eia.verify_key()
        assert ok
        assert "valid" in msg.lower()
