"""Tests for the Finnhub adapter (requires FINNHUB_API_KEY)."""

from __future__ import annotations

import os
import pytest
from econscope.adapters.finnhub import FinnhubAdapter


@pytest.fixture
def finnhub():
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        pytest.skip("FINNHUB_API_KEY not set")
    return FinnhubAdapter()


class TestFinnhubSearch:
    def test_search_apple(self, finnhub):
        results = finnhub.search("Apple")
        assert len(results) >= 1
        assert all(r.source == "finnhub" for r in results)
        # Should find AAPL
        symbols = [r.series_id for r in results]
        assert any("AAPL" in s for s in symbols)


class TestFinnhubPull:
    def test_pull_candle(self, finnhub):
        result = finnhub.pull_series("candle:AAPL", start="2024-01-01", end="2024-03-31")
        # Free tier may not support candles (403)
        if result.ok:
            assert result.count > 0
            obs = result.observations[0]
            assert "date" in obs
            assert "value" in obs
            assert isinstance(obs["value"], float)
        else:
            assert "403" in result.error or "Forbidden" in result.error

    def test_pull_quote(self, finnhub):
        result = finnhub.pull_series("quote:AAPL")
        assert result.ok
        assert result.count == 1
        obs = result.observations[0]
        assert obs["value"] > 0

    def test_pull_quote_has_ohlc(self, finnhub):
        result = finnhub.pull_series("quote:AAPL")
        assert result.ok
        obs = result.observations[0]
        assert "open" in obs
        assert "high" in obs
        assert "low" in obs


class TestFinnhubMetadata:
    def test_get_metadata(self, finnhub):
        meta = finnhub.get_metadata("candle:AAPL")
        assert meta.source == "finnhub"
        assert "AAPL" in meta.title or "Apple" in meta.title


class TestFinnhubVerify:
    def test_verify_key(self, finnhub):
        ok, msg = finnhub.verify_key()
        assert ok
        assert "valid" in msg.lower()
