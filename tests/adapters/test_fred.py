"""Tests for the FRED adapter (requires FRED_API_KEY)."""

from __future__ import annotations

import pytest
from econscope.adapters.fred import FREDAdapter


def test_fred_uses_public_graph_csv_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    adapter = FREDAdapter()
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return b"observation_date,PCEPI\n2025-07-01,126.0\n2026-07-01,130.2\n"

    monkeypatch.setattr(adapter, "_http_get", fake_get)
    result = adapter.pull_series("PCEPI", start="2025-01-01", end="2026-12-31")

    assert result.ok
    assert result.count == 2
    assert result.observations[-1] == {"date": "2026-07-01", "value": 130.2}
    assert "fredgraph.csv" in seen["url"]
    assert "cosd=2025-01-01" in seen["url"]
    assert "coed=2026-12-31" in seen["url"]


def test_fred_search_without_key_uses_curated_public_series(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    results = FREDAdapter().search("personal consumption")
    assert any(result.series_id == "PCEPI" for result in results)


@pytest.fixture
def fred(has_fred_key):
    return FREDAdapter()


class TestFREDSearch:
    def test_search_returns_results(self, fred):
        results = fred.search("unemployment rate", limit=5)
        assert len(results) > 0
        assert any("nemploy" in r.title.lower() for r in results)

    def test_search_returns_series_metadata(self, fred):
        results = fred.search("GDP", limit=3)
        r = results[0]
        assert r.source == "fred"
        assert r.series_id != ""
        assert r.title != ""


class TestFREDPull:
    def test_pull_gdp(self, fred):
        result = fred.pull_series("GDP", start="2023-01-01")
        assert result.ok
        assert result.count > 0
        assert result.source == "fred"
        assert result.series_id == "GDP"

        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)

    def test_pull_with_date_range(self, fred):
        result = fred.pull_series("UNRATE", start="2024-01-01", end="2024-06-30")
        assert result.ok
        assert result.count >= 1
        # All dates within range
        for obs in result.observations:
            assert obs["date"] >= "2024-01-01"
            assert obs["date"] <= "2024-06-30"

    def test_pull_bad_series(self, fred):
        result = fred.pull_series("NONEXISTENT_SERIES_XYZ")
        assert not result.ok
        assert result.error is not None


class TestFREDMetadata:
    def test_get_metadata(self, fred):
        meta = fred.get_metadata("UNRATE")
        assert meta.series_id == "UNRATE"
        assert "nemploy" in meta.title.lower() or "unemployment" in meta.title.lower()
        assert meta.frequency != ""
        assert meta.units != ""

    def test_get_categories(self, fred):
        cats = fred.get_categories("UNRATE")
        assert len(cats) > 0


class TestFREDPullResult:
    def test_raw_bytes_returned(self, fred):
        result = fred.pull_series("GDP", start="2024-01-01")
        assert len(result.raw_bytes) > 0
        assert result.metadata is not None
        assert result.metadata.title != ""
