"""Tests for the UN Comtrade adapter (requires COMTRADE_API_KEY)."""

from __future__ import annotations

import os
import pytest
from econscope.adapters.comtrade import ComtradeAdapter, COMMON_QUERIES


@pytest.fixture
def comtrade():
    key = os.environ.get("COMTRADE_API_KEY")
    if not key:
        pytest.skip("COMTRADE_API_KEY not set")
    return ComtradeAdapter()


class TestComtradeSearch:
    def test_search_exports(self, comtrade):
        results = comtrade.search("exports")
        assert len(results) >= 1
        assert all(r.source == "comtrade" for r in results)

    def test_search_china(self, comtrade):
        results = comtrade.search("china")
        assert len(results) >= 1

    def test_common_queries_populated(self):
        assert len(COMMON_QUERIES) >= 5
        assert "us_total_exports" in COMMON_QUERIES
        assert "us_china_imports" in COMMON_QUERIES


class TestComtradePull:
    def test_pull_us_exports(self, comtrade):
        result = comtrade.pull_series("us_total_exports", start="2022-01-01", end="2022-12-31")
        assert result.ok
        assert result.count > 0
        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)

    def test_pull_bad_series(self, comtrade):
        result = comtrade.pull_series("bad_format_no_colons")
        assert not result.ok


class TestComtradeMetadata:
    def test_get_metadata_common(self, comtrade):
        meta = comtrade.get_metadata("us_total_exports")
        assert meta.source == "comtrade"
        assert "Export" in meta.title


class TestComtradeVerify:
    def test_verify_key(self, comtrade):
        ok, msg = comtrade.verify_key()
        assert ok
        assert "valid" in msg.lower()
