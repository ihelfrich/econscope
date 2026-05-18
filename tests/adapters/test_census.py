"""Tests for the Census adapter (requires CENSUS_API_KEY)."""

from __future__ import annotations

import os
import pytest
from econscope.adapters.census import CensusAdapter, COMMON_DATASETS


@pytest.fixture
def census():
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        pytest.skip("CENSUS_API_KEY not set")
    return CensusAdapter()


class TestCensusSearch:
    def test_search_population(self, census):
        results = census.search("population")
        assert len(results) >= 1
        assert all(r.source == "census" for r in results)

    def test_search_income(self, census):
        results = census.search("income")
        assert len(results) >= 1

    def test_common_datasets_populated(self):
        assert len(COMMON_DATASETS) >= 7
        assert "acs_population" in COMMON_DATASETS
        assert "acs_median_income" in COMMON_DATASETS


class TestCensusPull:
    def test_pull_population(self, census):
        result = census.pull_series("acs_population", start="2022-01-01", end="2022-12-31")
        assert result.ok
        assert result.count >= 50  # at least 50 states
        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert "geo_name" in obs
        assert isinstance(obs["value"], float)

    def test_pull_median_income(self, census):
        result = census.pull_series("acs_median_income", start="2022-01-01", end="2022-12-31")
        assert result.ok
        assert result.count >= 50

    def test_pull_bad_series(self, census):
        result = census.pull_series("nonexistent_garbage")
        assert not result.ok
        assert "unknown" in result.error.lower() or "format" in result.error.lower()


class TestCensusMetadata:
    def test_get_metadata_common(self, census):
        meta = census.get_metadata("acs_population")
        assert meta.source == "census"
        assert "Population" in meta.title

    def test_get_metadata_unknown(self, census):
        meta = census.get_metadata("unknown_thing")
        assert meta.source == "census"


class TestCensusVerify:
    def test_verify_key(self, census):
        ok, msg = census.verify_key()
        assert ok
        assert "valid" in msg.lower()
