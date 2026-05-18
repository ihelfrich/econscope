"""Tests for the DBnomics adapter (no key required)."""

from __future__ import annotations

import pytest
from econscope.adapters.dbnomics import DBnomicsAdapter, COMMON_SERIES


@pytest.fixture
def dbn():
    return DBnomicsAdapter()


class TestDBnomicsSearch:
    def test_search_exchange(self, dbn):
        results = dbn.search("exchange")
        assert len(results) >= 1
        assert all(r.source == "dbnomics" for r in results)

    def test_search_ecb(self, dbn):
        results = dbn.search("ecb")
        assert len(results) >= 1

    def test_common_series_populated(self):
        assert len(COMMON_SERIES) >= 7
        assert "ecb_eurusd" in COMMON_SERIES


class TestDBnomicsPull:
    def test_pull_eurusd(self, dbn):
        result = dbn.pull_series("ecb_eurusd", start="2024-01-01")
        assert result.ok
        assert result.count > 0
        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)

    def test_pull_raw_dbnomics_id(self, dbn):
        result = dbn.pull_series("ECB/EXR/M.USD.EUR.SP00.A", start="2023-01-01")
        assert result.ok
        assert result.count > 0

    def test_pull_observations_sorted(self, dbn):
        result = dbn.pull_series("ecb_eurusd", start="2020-01-01")
        assert result.ok
        dates = [o["date"] for o in result.observations]
        assert dates == sorted(dates)


class TestDBnomicsHelpers:
    def test_parse_period_annual(self):
        assert DBnomicsAdapter._parse_period("2024") == "2024-01-01"

    def test_parse_period_monthly(self):
        assert DBnomicsAdapter._parse_period("2024-03") == "2024-03-01"

    def test_parse_period_quarterly(self):
        assert DBnomicsAdapter._parse_period("2024-Q1") == "2024-01-01"
        assert DBnomicsAdapter._parse_period("2024-Q3") == "2024-07-01"

    def test_parse_period_daily(self):
        assert DBnomicsAdapter._parse_period("2024-03-15") == "2024-03-15"

    def test_parse_period_empty(self):
        assert DBnomicsAdapter._parse_period("") is None
        assert DBnomicsAdapter._parse_period(None) is None


class TestDBnomicsVerify:
    def test_verify_key(self, dbn):
        ok, msg = dbn.verify_key()
        assert ok
        assert "accessible" in msg.lower()
