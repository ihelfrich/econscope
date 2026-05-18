"""Tests for the Treasury FiscalData adapter (no key required)."""

from __future__ import annotations

import pytest
from econscope.adapters.treasury import TreasuryAdapter, COMMON_DATASETS


@pytest.fixture
def treasury():
    return TreasuryAdapter()


class TestTreasurySearch:
    def test_search_debt(self, treasury):
        results = treasury.search("debt")
        assert len(results) >= 2
        assert all(r.source == "treasury" for r in results)

    def test_search_rates(self, treasury):
        results = treasury.search("rates")
        assert len(results) >= 1

    def test_search_no_match(self, treasury):
        results = treasury.search("zzz_nonexistent_zzz")
        assert len(results) == 0

    def test_common_datasets_populated(self):
        assert len(COMMON_DATASETS) >= 8
        assert "debt_to_penny" in COMMON_DATASETS
        assert "avg_interest_rates" in COMMON_DATASETS


class TestTreasuryPull:
    def test_pull_debt_to_penny(self, treasury):
        result = treasury.pull_series("debt_to_penny", start="2024-01-01")
        assert result.ok
        assert result.count > 0
        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)

    def test_pull_avg_interest_rates(self, treasury):
        result = treasury.pull_series("avg_interest_rates", start="2024-01-01")
        assert result.ok
        assert result.count > 0

    def test_pull_observations_sorted(self, treasury):
        result = treasury.pull_series("debt_to_penny", start="2023-01-01")
        assert result.ok
        dates = [o["date"] for o in result.observations]
        assert dates == sorted(dates)

    def test_pull_with_date_range(self, treasury):
        result = treasury.pull_series(
            "debt_to_penny", start="2024-01-01", end="2024-06-30"
        )
        assert result.ok
        for obs in result.observations:
            assert obs["date"] >= "2024-01-01"
            assert obs["date"] <= "2024-06-30"

    def test_pull_raw_bytes(self, treasury):
        result = treasury.pull_series("debt_to_penny", start="2024-01-01")
        assert result.ok
        assert len(result.raw_bytes) > 0


class TestTreasuryMetadata:
    def test_get_metadata_common(self, treasury):
        meta = treasury.get_metadata("debt_to_penny")
        assert meta.source == "treasury"
        assert "Debt" in meta.title

    def test_get_metadata_unknown(self, treasury):
        meta = treasury.get_metadata("unknown_endpoint")
        assert meta.source == "treasury"
        assert meta.series_id == "unknown_endpoint"


class TestTreasuryVerify:
    def test_verify_key(self, treasury):
        ok, msg = treasury.verify_key()
        assert ok
        assert "accessible" in msg.lower() or "no key" in msg.lower()
