"""Tests for the BLS adapter (requires BLS_API_KEY)."""

from __future__ import annotations

import pytest
from econscope.adapters.bls import BLSAdapter, COMMON_SERIES


@pytest.fixture
def bls(has_bls_key):
    return BLSAdapter()


class TestBLSSearch:
    def test_search_cpi(self, bls):
        results = bls.search("CPI")
        assert len(results) > 0
        assert all(r.source == "bls" for r in results)

    def test_search_employment(self, bls):
        results = bls.search("employment")
        assert len(results) > 0

    def test_search_no_match(self, bls):
        results = bls.search("zzzznonexistentzzz")
        assert len(results) == 0

    def test_common_series_populated(self):
        assert len(COMMON_SERIES) >= 15
        assert "Total Nonfarm Employment" in COMMON_SERIES
        assert "Unemployment Rate" in COMMON_SERIES


class TestBLSPull:
    def test_pull_unemployment(self, bls):
        result = bls.pull_series("LNS14000000", start="2024-01-01")
        assert result.ok
        assert result.count > 0
        assert result.source == "bls"

        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)

    def test_pull_nonfarm(self, bls):
        result = bls.pull_series("CES0000000001", start="2024-01-01")
        assert result.ok
        assert result.count >= 1

    def test_pull_with_date_range(self, bls):
        result = bls.pull_series("LNS14000000", start="2023-01-01", end="2023-12-31")
        assert result.ok
        for obs in result.observations:
            assert obs["date"] >= "2023-01-01"
            assert obs["date"] <= "2023-12-31"

    def test_observations_sorted(self, bls):
        result = bls.pull_series("LNS14000000", start="2022-01-01", end="2024-01-01")
        assert result.ok
        dates = [o["date"] for o in result.observations]
        assert dates == sorted(dates)


class TestBLSBatch:
    def test_batch_pull(self, bls):
        ids = ["LNS14000000", "CES0000000001"]
        results = bls.pull_batch(ids, start="2024-01-01")
        assert len(results) == 2
        assert all(r.ok for r in results)
        assert {r.series_id for r in results} == set(ids)


class TestBLSMetadata:
    def test_get_metadata(self, bls):
        meta = bls.get_metadata("CES0000000001")
        assert meta.series_id == "CES0000000001"
        assert meta.source == "bls"
