"""CoinGecko adapter — cryptocurrency prices, market data, DeFi metrics.

API docs: https://docs.coingecko.com/reference/introduction

Free Demo plan: 30 calls/min, 10K calls/month. No key needed for basic endpoints.
"""

from __future__ import annotations

import json
from typing import Optional
from datetime import datetime
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import get_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_COINS = {
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
    "tether": "Tether (USDT)",
    "solana": "Solana",
    "ripple": "XRP",
    "cardano": "Cardano",
    "dogecoin": "Dogecoin",
    "polkadot": "Polkadot",
    "chainlink": "Chainlink",
    "avalanche-2": "Avalanche",
}


class CoinGeckoAdapter(BaseAdapter):
    source_id = "coingecko"
    source_name = "CoinGecko"
    key_env_var = ""  # Basic endpoints don't need a key
    requests_per_minute = 25  # conservative under 30/min limit

    BASE = "https://api.coingecko.com/api/v3"

    def __init__(self):
        self.api_key = get_key("COINGECKO_API_KEY")  # optional

    def _get(self, endpoint: str, **params) -> tuple[dict | list, bytes]:
        if self.api_key:
            params["x_cg_demo_api_key"] = self.api_key
        url = f"{self.BASE}/{endpoint}"
        if params:
            url += f"?{urlencode(params)}"
        from urllib.request import Request
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0 (economic research platform)")
        req.add_header("Accept", "application/json")
        raw = urlopen(req).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull crypto price history from CoinGecko.

        series_id: coin ID (e.g., "bitcoin", "ethereum", "solana")
        """
        coin_id = series_id.lower()
        title = COMMON_COINS.get(coin_id, coin_id.title())

        params = {"vs_currency": "usd"}

        if start and end:
            start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
            end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp())
            params["from"] = str(start_ts)
            params["to"] = str(end_ts)
            endpoint = f"coins/{coin_id}/market_chart/range"
        else:
            # Default: last 365 days
            days = 365
            if start:
                delta = (datetime.now() - datetime.strptime(start, "%Y-%m-%d")).days
                days = max(1, delta)
            params["days"] = str(days)
            endpoint = f"coins/{coin_id}/market_chart"

        try:
            data, raw = self._get(endpoint, **params)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        prices = data.get("prices", []) if isinstance(data, dict) else []

        observations = []
        seen_dates = set()
        for ts_ms, price in prices:
            dt = datetime.utcfromtimestamp(ts_ms / 1000)
            date_str = dt.strftime("%Y-%m-%d")
            if date_str in seen_dates:
                continue
            seen_dates.add(date_str)
            observations.append({"date": date_str, "value": float(price)})

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title} Price (USD)", frequency="Daily", units="USD",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for coins."""
        query_lower = query.lower()
        results = []
        # Check common coins first
        for coin_id, name in COMMON_COINS.items():
            if query_lower in name.lower() or query_lower in coin_id:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=coin_id,
                    title=f"{name} Price (USD)", units="USD",
                ))

        if len(results) >= limit:
            return results[:limit]

        # Hit CoinGecko search
        try:
            data, _ = self._get("search", query=query)
            seen = {r.series_id for r in results}
            for coin in data.get("coins", [])[:limit]:
                cid = coin.get("id", "")
                if cid in seen:
                    continue
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=cid,
                    title=f"{coin.get('name', cid)} Price (USD)",
                    notes=f"Symbol: {coin.get('symbol', '')}",
                ))
        except Exception:
            pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        coin_id = series_id.lower()
        if coin_id in COMMON_COINS:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=f"{COMMON_COINS[coin_id]} Price (USD)",
                frequency="Daily", units="USD",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("simple/price", ids="bitcoin", vs_currencies="usd")
            btc = data.get("bitcoin", {}).get("usd")
            if btc:
                return True, f"CoinGecko: API accessible (BTC=${btc:,.0f})"
            return False, "CoinGecko: no data returned"
        except Exception as e:
            return False, f"CoinGecko: {e}"
