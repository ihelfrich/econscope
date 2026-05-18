"""Tests for the World Bank adapter (no key required)."""

from __future__ import annotations

import pytest
from econscope.adapters.worldbank import WorldBankAdapter, COMMON_INDICATORS


@pytest.fixture
def wb():
    return WorldBankAdapter()


class TestWorldBankSearch:
    def test_search_gdp(self, wb):
        results = wb.search("GDP")
        assert len(results) >= 1
        assert all(r.source == "worldbank" for r in results)

    def test_search_poverty(self, wb):
        results = wb.search("poverty")
        assert len(results) >= 1

    def test_search_api(self, wb):
        # Should hit the API for non-common terms
        results = wb.search("renewable energy")
        assert len(results) >= 1

    def test_common_indicators_populated(self):
        assert len(COMMON_INDICATORS) >= 25
        assert "NY.GDP.MKTP.CD" in COMMON_INDICATORS
        assert "SI.POV.GINI" in COMMON_INDICATORS


class TestWorldBankPull:
    def test_pull_gdp_usa(self, wb):
        result = wb.pull_series("USA:NY.GDP.MKTP.CD", start="2020-01-01")
        assert result.ok
        assert result.count > 0
        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)
        assert obs["value"] > 1e12  # US GDP > $1 trillion

    def test_pull_gdp_all_countries(self, wb):
        result = wb.pull_series("NY.GDP.MKTP.CD", start="2022-01-01", end="2022-12-31")
        assert result.ok
        assert result.count > 50  # Many countries
        # Check geo info
        assert "geo_name" in result.observations[0]

    def test_pull_observations_sorted(self, wb):
        result = wb.pull_series("USA:NY.GDP.MKTP.CD", start="2010-01-01")
        assert result.ok
        dates = [o["date"] for o in result.observations]
        assert dates == sorted(dates)

    def test_pull_with_date_range(self, wb):
        result = wb.pull_series("USA:SP.POP.TOTL", start="2020-01-01", end="2022-12-31")
        assert result.ok
        assert result.count >= 1


class TestWorldBankMetadata:
    def test_get_metadata_common(self, wb):
        meta = wb.get_metadata("NY.GDP.MKTP.CD")
        assert meta.source == "worldbank"
        assert "GDP" in meta.title

    def test_get_metadata_api(self, wb):
        meta = wb.get_metadata("SP.POP.TOTL")
        assert meta.source == "worldbank"
        assert "Population" in meta.title


class TestWorldBankVerify:
    def test_verify_key(self, wb):
        ok, msg = wb.verify_key()
        assert ok
        assert "accessible" in msg.lower()
