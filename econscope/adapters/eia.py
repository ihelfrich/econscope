"""EIA adapter — Energy Information Administration (crude oil, natural gas, electricity, coal).

API v2 docs: https://www.eia.gov/opendata/documentation.php

Key design notes:
- Base URL: https://api.eia.gov/v2/
- Hierarchical routes: petroleum/pri/spt = petroleum > prices > spot prices
- Append /data to any route to get time series
- Values are strings, not numbers
- Max 5000 rows per response (paginate with offset)
- No published rate limit; stay under ~2 req/sec
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common EIA series routes with human-readable names
COMMON_ROUTES = {
    # Petroleum
    "crude_wti": (
        "petroleum/pri/spt",
        "WTI Crude Oil Spot Price",
        {"facets[product][]": "EPCWTI"},
        "value",
    ),
    "crude_brent": (
        "petroleum/pri/spt",
        "Brent Crude Oil Spot Price",
        {"facets[product][]": "EPCBRENT"},
        "value",
    ),
    "gasoline_regular": (
        "petroleum/pri/gnd",
        "US Regular Gasoline Prices",
        {"facets[product][]": "EPM0", "facets[duoarea][]": "NUS"},
        "value",
    ),
    "crude_production": (
        "petroleum/crd/crpdn",
        "US Crude Oil Production",
        {"facets[duoarea][]": "NUS"},
        "value",
    ),
    "petroleum_stocks": (
        "petroleum/stoc/wstk",
        "US Weekly Petroleum Stocks",
        {"facets[product][]": "EPC0", "facets[duoarea][]": "NUS"},
        "value",
    ),
    # Natural gas
    "natgas_price": (
        "natural-gas/pri/sum",
        "Natural Gas Prices Summary",
        {"facets[duoarea][]": "NUS", "facets[process][]": "PCS"},
        "value",
    ),
    "henry_hub": (
        "natural-gas/pri/fut",
        "Henry Hub Natural Gas Futures",
        {"facets[duoarea][]": "NUS", "facets[process][]": "PCS"},
        "value",
    ),
    # Electricity
    "electricity_price": (
        "electricity/retail-sales",
        "Average Retail Price of Electricity",
        {"facets[sectorid][]": "RES", "facets[stateid][]": "US"},
        "price",
    ),
    "electricity_generation": (
        "electricity/electric-power-operational-data",
        "Electricity Net Generation",
        {"facets[fueltypeid][]": "ALL", "facets[location][]": "US"},
        "generation",
    ),
    # Coal
    "coal_production": (
        "coal/mine-production",
        "Coal Mine Production",
        {},
        "production",
    ),
    # Total energy
    "total_energy_consumption": (
        "total-energy/data",
        "Total Energy Consumption",
        {"facets[msn][]": "TETCBUS"},
        "value",
    ),
}


class EIAAdapter(BaseAdapter):
    source_id = "eia"
    source_name = "EIA"
    key_env_var = "EIA_API_KEY"
    requests_per_minute = 60

    BASE = "https://api.eia.gov/v2"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, route: str, params: dict = None) -> tuple[dict, bytes]:
        """GET from EIA API v2."""
        all_params = {"api_key": self.api_key}
        if params:
            all_params.update(params)
        url = f"{self.BASE}/{route}?{urlencode(all_params, doseq=True)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def _get_data(self, route: str, data_col: str = "value",
                  facets: dict = None, start: str = None, end: str = None,
                  frequency: str = "monthly", length: int = 5000) -> tuple[dict, bytes]:
        """Fetch from a /data endpoint."""
        params = {
            "api_key": self.api_key,
            "data[0]": data_col,
            "frequency": frequency,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": str(length),
        }
        if facets:
            params.update(facets)
        if start:
            params["start"] = start[:7] if frequency == "monthly" else start[:4] if frequency == "annual" else start
        if end:
            params["end"] = end[:7] if frequency == "monthly" else end[:4] if frequency == "annual" else end

        url = f"{self.BASE}/{route}/data?{urlencode(params, doseq=True)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def browse(self, route: str = "") -> dict:
        """Browse the EIA route hierarchy. Returns available sub-routes and facets."""
        data, _ = self._get(route)
        return data.get("response", {})

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from EIA.

        series_id can be:
          - A common name: "crude_wti", "natgas_price"
          - A raw route: "petroleum/pri/spt" (will use default value column)
        """
        if series_id in COMMON_ROUTES:
            route, title, facets, data_col = COMMON_ROUTES[series_id]
        else:
            route = series_id
            title = series_id
            facets = {}
            data_col = "value"

        # Try weekly, monthly, annual — some series only have certain frequencies
        for freq in ["weekly", "monthly", "annual"]:
            try:
                data, raw = self._get_data(
                    route, data_col=data_col, facets=facets,
                    start=start, end=end, frequency=freq,
                )
                resp = data.get("response", {})
                if resp.get("data"):
                    break
            except Exception:
                if freq == "annual":
                    raise
                continue

        resp = data.get("response", {})
        rows = resp.get("data", [])

        observations = []
        for row in rows:
            period = row.get("period", "")
            if not period:
                continue
            date_str = self._parse_period(period)
            if not date_str:
                continue

            raw_val = row.get(data_col, "")
            try:
                value = float(str(raw_val).replace(",", ""))
            except (ValueError, TypeError):
                continue

            observations.append({"date": date_str, "value": value})

        observations.sort(key=lambda x: x["date"])

        units = ""
        if rows:
            units = rows[0].get(f"{data_col}-units", "")

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=title,
            frequency=resp.get("frequency", ""),
            units=units,
            notes=f"Route: {route}",
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
        """Search common EIA routes by keyword."""
        query_lower = query.lower()
        results = []
        for route_id, (route, title, _, _) in COMMON_ROUTES.items():
            if query_lower in title.lower() or query_lower in route_id.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=route_id,
                    title=title,
                    notes=f"Route: {route}",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_ROUTES:
            route, title, _, _ = COMMON_ROUTES[series_id]
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=title,
                notes=f"Route: {route}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("")
            resp = data.get("response", {})
            routes = resp.get("routes", [])
            if routes:
                return True, f"EIA: key valid ({len(routes)} top-level routes)"
            return False, "EIA: no routes returned"
        except Exception as e:
            return False, f"EIA: {e}"

    @staticmethod
    def _parse_period(period: str) -> Optional[str]:
        """Convert EIA period to YYYY-MM-DD.

        Handles: "2024", "2024-03", "2024-03-15", "2024-W12"
        """
        if not period:
            return None
        period = period.strip()
        if len(period) == 4 and period.isdigit():
            return f"{period}-01-01"
        if len(period) == 7 and period[4] == "-":
            return f"{period}-01"
        if len(period) == 10 and period[4] == "-" and period[7] == "-":
            return period
        # Weekly: "2024-W12"
        if "W" in period:
            parts = period.split("-W")
            if len(parts) == 2:
                year = parts[0]
                week = int(parts[1])
                # Approximate: week 1 = Jan 1, each week = 7 days
                from datetime import date, timedelta
                d = date(int(year), 1, 1) + timedelta(weeks=week - 1)
                return d.isoformat()
        return None

    @staticmethod
    def list_common_routes() -> dict:
        return {k: v[1] for k, v in COMMON_ROUTES.items()}
