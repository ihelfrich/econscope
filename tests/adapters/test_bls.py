"""Tests for the BLS adapter (requires BLS_API_KEY)."""

from __future__ import annotations

import pytest
from econscope.adapters.bls import BLSAdapter, COMMON_SERIES


def test_bls_can_use_the_public_unregistered_signature(monkeypatch):
    """BLS v1-compatible requests are public; a key only unlocks v2 extras."""
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    adapter = BLSAdapter()
    captured = {}

    def fake_post(url, data, headers=None, timeout=None):
        import json
        captured.update(json.loads(data))
        return json.dumps({
            "status": "REQUEST_SUCCEEDED",
            "Results": {"series": [{
                "seriesID": "LNS14000000",
                "data": [{"year": "2026", "period": "M07", "value": "4.2"}],
            }]},
        }).encode()

    monkeypatch.setattr(adapter, "_http_post", fake_post)
    result = adapter.pull_series("LNS14000000", start="2026-01-01", end="2026-12-31")

    assert result.ok
    assert result.observations == [{"date": "2026-07-01", "value": 4.2}]
    assert "registrationkey" not in captured
    assert "catalog" not in captured
    assert result.metadata.title == "Unemployment Rate"


def test_bls_registered_signature_keeps_catalog_metadata(monkeypatch):
    monkeypatch.setenv("BLS_API_KEY", "test-registration-key")
    adapter = BLSAdapter()
    captured = {}

    def fake_post(url, data, headers=None, timeout=None):
        import json
        captured.update(json.loads(data))
        return json.dumps({
            "status": "REQUEST_SUCCEEDED",
            "Results": {"series": [{
                "seriesID": "LNS14000000",
                "catalog": {"series_title": "Unemployment Rate"},
                "data": [],
            }]},
        }).encode()

    monkeypatch.setattr(adapter, "_http_post", fake_post)
    adapter.pull_series("LNS14000000", start="2026-01-01", end="2026-12-31")

    assert captured["registrationkey"] == "test-registration-key"
    assert captured["catalog"] is True


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
