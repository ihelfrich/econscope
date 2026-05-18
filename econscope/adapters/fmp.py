"""FMP adapter — Financial Modeling Prep (financials, ratios, historical prices).

API docs: https://site.financialmodelingprep.com/developer/docs

Key design notes:
- Base URL: https://financialmodelingprep.com/api/v3/
- API key passed as query param apikey
- Free tier: 250 calls/day, delayed data
- Covers: income statements, balance sheets, cash flow, ratios, prices, ETFs
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


class FMPAdapter(BaseAdapter):
    source_id = "fmp"
    source_name = "FMP"
    key_env_var = "FMP_API_KEY"
    requests_per_minute = 60  # conservative; 250/day

    BASE = "https://financialmodelingprep.com/api/v3"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, endpoint: str, **params) -> tuple[dict | list, bytes]:
        params["apikey"] = self.api_key
        url = f"{self.BASE}/{endpoint}?{urlencode(params)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from FMP.

        series_id types:
          - Historical price: "price:AAPL"
          - Income statement: "income:AAPL" or "income:AAPL:annual"
          - Balance sheet: "balance:AAPL"
          - Cash flow: "cashflow:AAPL"
          - Ratios: "ratios:AAPL"
          - Treasury rate: "treasury"
          - Economic indicator: "economic:GDP" (GDP, CPI, unemployment, etc.)
        """
        parts = series_id.split(":")
        data_type = parts[0].lower() if parts else ""

        if data_type == "price" and len(parts) >= 2:
            return self._pull_price(series_id, parts[1], start, end)
        elif data_type == "income" and len(parts) >= 2:
            period = parts[2] if len(parts) > 2 else "annual"
            return self._pull_financials(series_id, "income-statement", parts[1], period, "revenue")
        elif data_type == "balance" and len(parts) >= 2:
            period = parts[2] if len(parts) > 2 else "annual"
            return self._pull_financials(series_id, "balance-sheet-statement", parts[1], period, "totalAssets")
        elif data_type == "cashflow" and len(parts) >= 2:
            period = parts[2] if len(parts) > 2 else "annual"
            return self._pull_financials(series_id, "cash-flow-statement", parts[1], period, "operatingCashFlow")
        elif data_type == "ratios" and len(parts) >= 2:
            return self._pull_ratios(series_id, parts[1])
        elif data_type == "treasury":
            return self._pull_treasury(series_id, start, end)
        elif data_type == "economic" and len(parts) >= 2:
            return self._pull_economic(series_id, parts[1], start, end)
        else:
            # Default: treat as historical price
            return self._pull_price(series_id, series_id, start, end)

    def _pull_price(self, series_id: str, symbol: str,
                    start: str = None, end: str = None) -> PullResult:
        """Pull historical daily prices."""
        params = {}
        if start:
            params["from"] = start
        if end:
            params["to"] = end

        try:
            data, raw = self._get(f"historical-price-full/{symbol}", **params)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        historical = data.get("historical", []) if isinstance(data, dict) else []

        observations = []
        for row in historical:
            date_str = row.get("date", "")
            close = row.get("close")
            if not date_str or close is None:
                continue
            obs = {"date": date_str, "value": float(close)}
            vol = row.get("volume")
            if vol is not None:
                obs["volume"] = vol
            observations.append(obs)

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"{symbol} Historical Stock Price",
            frequency="Daily",
            units="USD",
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

    def _pull_financials(self, series_id: str, statement: str, symbol: str,
                         period: str, value_field: str) -> PullResult:
        """Pull financial statements (income, balance, cash flow)."""
        params = {"period": period} if period == "quarter" else {}

        try:
            data, raw = self._get(f"{statement}/{symbol}", **params)
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
            value = row.get(value_field)
            if not date_str or value is None:
                continue
            observations.append({"date": date_str, "value": float(value)})

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"{symbol} {statement.replace('-', ' ').title()} ({value_field})",
            frequency="Quarterly" if period == "quarter" else "Annual",
            units="USD",
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

    def _pull_ratios(self, series_id: str, symbol: str) -> PullResult:
        """Pull financial ratios (P/E, ROE, etc.)."""
        try:
            data, raw = self._get(f"ratios/{symbol}")
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

        # Return P/E ratio as the primary value
        observations = []
        for row in data:
            date_str = row.get("date", "")
            pe = row.get("priceEarningsRatio")
            if not date_str or pe is None:
                continue
            observations.append({"date": date_str, "value": float(pe)})

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"{symbol} Financial Ratios (P/E)",
            frequency="Annual",
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

    def _pull_treasury(self, series_id: str,
                       start: str = None, end: str = None) -> PullResult:
        """Pull Treasury rate data."""
        params = {}
        if start:
            params["from"] = start
        if end:
            params["to"] = end

        try:
            data, raw = self._get("treasury", **params)
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
            # Use 10-year as default
            value = row.get("year10")
            if not date_str or value is None:
                continue
            observations.append({"date": date_str, "value": float(value)})

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title="Treasury Rates (10-Year)",
            frequency="Daily",
            units="Percent",
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

    def _pull_economic(self, series_id: str, indicator: str,
                       start: str = None, end: str = None) -> PullResult:
        """Pull economic indicators from FMP."""
        params = {"name": indicator}
        if start:
            params["from"] = start
        if end:
            params["to"] = end

        try:
            data, raw = self._get("economic", **params)
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
            observations.append({"date": date_str[:10], "value": float(value)})

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"Economic Indicator: {indicator}",
            notes=f"FMP economic indicator: {indicator}",
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

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for stock symbols."""
        try:
            data, _ = self._get("search", query=query, limit=limit)
            results = []
            for item in (data if isinstance(data, list) else [])[:limit]:
                symbol = item.get("symbol", "")
                name = item.get("name", "")
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"price:{symbol}",
                    title=f"{symbol} — {name}",
                    notes=item.get("exchangeShortName", ""),
                ))
            return results
        except Exception:
            return []

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        parts = series_id.split(":")
        if len(parts) >= 2 and parts[0].lower() == "price":
            symbol = parts[1]
            try:
                data, _ = self._get(f"profile/{symbol}")
                if isinstance(data, list) and data:
                    p = data[0]
                    return SeriesMetadata(
                        source=self.source_id,
                        series_id=series_id,
                        title=f"{symbol} — {p.get('companyName', '')}",
                        notes=f"Sector: {p.get('sector', '')}, Industry: {p.get('industry', '')}",
                    )
            except Exception:
                pass
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("quote/AAPL")
            if isinstance(data, list) and data:
                price = data[0].get("price", "N/A")
                return True, f"FMP: key valid (AAPL=${price})"
            return False, "FMP: no quote returned"
        except Exception as e:
            return False, f"FMP: {e}"
