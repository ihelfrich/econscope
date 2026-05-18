"""Finnhub adapter — real-time stock prices, fundamentals, and economic indicators.

API docs: https://finnhub.io/docs/api

Key design notes:
- Base URL: https://finnhub.io/api/v1/
- Token passed as query param or X-Finnhub-Token header
- Free tier: 60 calls/min, 30 calls/sec
- Stock candles, company profiles, economic calendar, economic codes
"""

from __future__ import annotations

import json
from datetime import datetime, date, timedelta
from typing import List, Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


class FinnhubAdapter(BaseAdapter):
    source_id = "finnhub"
    source_name = "Finnhub"
    key_env_var = "FINNHUB_API_KEY"
    requests_per_minute = 60

    BASE = "https://finnhub.io/api/v1"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, endpoint: str, **params) -> tuple[dict | list, bytes]:
        params["token"] = self.api_key
        url = f"{self.BASE}/{endpoint}?{urlencode(params)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from Finnhub.

        series_id types:
          - Stock candle: "candle:AAPL" or "candle:AAPL:D" (resolution: 1, 5, 15, 30, 60, D, W, M)
          - Quote: "quote:AAPL" (latest price)
          - Economic: "economic:INDICATOR_CODE" (economic indicators)
        """
        parts = series_id.split(":")
        data_type = parts[0].lower() if parts else ""

        if data_type == "candle" and len(parts) >= 2:
            symbol = parts[1]
            resolution = parts[2] if len(parts) > 2 else "D"
            return self._pull_candle(series_id, symbol, resolution, start, end)
        elif data_type == "quote" and len(parts) >= 2:
            symbol = parts[1]
            return self._pull_quote(series_id, symbol)
        elif data_type == "economic" and len(parts) >= 2:
            code = parts[1]
            return self._pull_economic(series_id, code)
        else:
            # Default: treat as stock candle
            return self._pull_candle(series_id, series_id, "D", start, end)

    def _pull_candle(self, series_id: str, symbol: str, resolution: str,
                     start: str = None, end: str = None) -> PullResult:
        """Pull stock candle data."""
        end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp()) if end else int(datetime.now().timestamp())
        start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp()) if start else end_ts - (365 * 86400)

        try:
            data, raw = self._get(
                "stock/candle",
                symbol=symbol,
                resolution=resolution,
                **{"from": str(start_ts), "to": str(end_ts)},
            )
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        if not isinstance(data, dict) or data.get("s") == "no_data":
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error="No candle data returned",
                raw_bytes=raw if isinstance(raw, bytes) else b"",
            )

        closes = data.get("c", [])
        timestamps = data.get("t", [])
        volumes = data.get("v", [])

        observations = []
        for i, (ts, close) in enumerate(zip(timestamps, closes)):
            dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            obs = {"date": dt, "value": float(close)}
            if i < len(volumes):
                obs["volume"] = volumes[i]
            observations.append(obs)

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"{symbol} Stock Price (Close)",
            frequency="Daily" if resolution == "D" else resolution,
            units="USD",
            notes=f"Symbol: {symbol}, Resolution: {resolution}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=observations,
            raw_bytes=raw,
        )

    def _pull_quote(self, series_id: str, symbol: str) -> PullResult:
        """Pull latest quote."""
        try:
            data, raw = self._get("quote", symbol=symbol)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        if not data.get("c"):
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error="No quote data returned",
                raw_bytes=raw,
            )

        today = date.today().isoformat()
        obs = {
            "date": today,
            "value": float(data["c"]),
            "open": float(data.get("o", 0)),
            "high": float(data.get("h", 0)),
            "low": float(data.get("l", 0)),
            "prev_close": float(data.get("pc", 0)),
        }

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"{symbol} Current Quote",
            units="USD",
        )

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=[obs],
            raw_bytes=raw,
        )

    def _pull_economic(self, series_id: str, code: str) -> PullResult:
        """Pull economic indicator data from Finnhub."""
        try:
            data, raw = self._get("economic", code=code)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        if not isinstance(data, list):
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error="Unexpected response format",
                raw_bytes=raw,
            )

        observations = []
        for row in data:
            date_str = row.get("date", "")
            value = row.get("value")
            if not date_str or value is None:
                continue
            try:
                observations.append({
                    "date": date_str[:10],
                    "value": float(value),
                })
            except (ValueError, TypeError):
                continue

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"Economic Indicator: {code}",
            notes=f"Finnhub economic code: {code}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=observations,
            raw_bytes=raw,
        )

    def get_company_profile(self, symbol: str) -> dict:
        """Get company profile (name, market cap, industry, etc.)."""
        data, _ = self._get("stock/profile2", symbol=symbol)
        return data

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for stock symbols."""
        try:
            data, _ = self._get("search", q=query)
            results = []
            for item in data.get("result", [])[:limit]:
                symbol = item.get("symbol", "")
                desc = item.get("description", "")
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"candle:{symbol}",
                    title=f"{symbol} — {desc}",
                    notes=item.get("type", ""),
                ))
            return results
        except Exception:
            return []

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        parts = series_id.split(":")
        if len(parts) >= 2 and parts[0].lower() in ("candle", "quote"):
            symbol = parts[1]
            try:
                profile = self.get_company_profile(symbol)
                return SeriesMetadata(
                    source=self.source_id,
                    series_id=series_id,
                    title=f"{symbol} — {profile.get('name', '')}",
                    notes=f"Industry: {profile.get('finnhubIndustry', '')}, Market Cap: {profile.get('marketCapitalization', '')}M",
                )
            except Exception:
                pass
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("quote", symbol="AAPL")
            if data.get("c"):
                return True, f"Finnhub: key valid (AAPL=${data['c']})"
            return False, "Finnhub: no quote returned"
        except Exception as e:
            return False, f"Finnhub: {e}"
