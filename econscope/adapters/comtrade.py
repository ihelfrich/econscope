"""UN Comtrade adapter — international trade data (imports, exports by commodity and partner).

API docs: https://comtradeapi.un.org/files/v1/app/reference/ListofReferences.json

Key design notes:
- Base URL: https://comtradeapi.un.org/data/v1/get/C/A/
- Subscription key passed as Ocp-Apim-Subscription-Key header
- HS commodity codes, reporter/partner country codes
- Covers: bilateral trade flows, commodity-level detail
- This is trade data — Ian's bread and butter
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common trade queries
COMMON_QUERIES = {
    "us_total_exports": {
        "title": "US Total Exports",
        "reporter": "842",  # USA
        "partner": "0",  # World
        "flow": "X",
        "commodity": "TOTAL",
    },
    "us_total_imports": {
        "title": "US Total Imports",
        "reporter": "842",  # USA
        "partner": "0",  # World
        "flow": "M",
        "commodity": "TOTAL",
    },
    "us_china_exports": {
        "title": "US Exports to China",
        "reporter": "842",
        "partner": "156",  # China
        "flow": "X",
        "commodity": "TOTAL",
    },
    "us_china_imports": {
        "title": "US Imports from China",
        "reporter": "842",
        "partner": "156",
        "flow": "M",
        "commodity": "TOTAL",
    },
    "world_crude_oil": {
        "title": "World Crude Oil Trade (HS 2709)",
        "reporter": "0",  # World
        "partner": "0",
        "flow": "M",
        "commodity": "2709",
    },
}


class ComtradeAdapter(BaseAdapter):
    source_id = "comtrade"
    source_name = "UN Comtrade"
    key_env_var = "COMTRADE_API_KEY"
    requests_per_minute = 30

    BASE = "https://comtradeapi.un.org/data/v1/get/C/A"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, **params) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{params.pop('reporter', '842')}/{params.pop('year', 'recent')}"
        if params:
            url += f"?{urlencode(params)}"
        req = Request(url)
        req.add_header("Ocp-Apim-Subscription-Key", self.api_key)
        raw = urlopen(req).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from UN Comtrade.

        series_id can be:
          - A common name: "us_total_exports", "us_china_imports"
          - Custom format: "REPORTER:PARTNER:FLOW:COMMODITY"
            e.g., "842:156:M:TOTAL" = US imports from China, all commodities
        """
        if series_id in COMMON_QUERIES:
            q = COMMON_QUERIES[series_id]
            reporter = q["reporter"]
            partner = q["partner"]
            flow = q["flow"]
            commodity = q["commodity"]
            title = q["title"]
        else:
            parts = series_id.split(":")
            if len(parts) == 4:
                reporter, partner, flow, commodity = parts
                title = f"Trade flow {reporter}→{partner} ({flow}, {commodity})"
            else:
                return PullResult(
                    source=self.source_id,
                    series_id=series_id,
                    metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                    error=(
                        f"Unknown series_id: '{series_id}'. "
                        "Use a common name or REPORTER:PARTNER:FLOW:COMMODITY format."
                    ),
                )

        # Build year range
        start_year = int(start[:4]) if start else 2010
        end_year = int(end[:4]) if end else 2024

        all_obs = []
        raw_parts = []

        # Comtrade limits to 5 years per request in some cases
        for year in range(start_year, end_year + 1):
            try:
                params = {
                    "reporter": reporter,
                    "year": str(year),
                    "partnerCode": partner,
                    "flowCode": flow,
                    "cmdCode": commodity,
                }
                data, raw = self._get(**params)
                raw_parts.append(raw)
            except Exception:
                continue

            rows = data.get("data", [])
            for row in rows:
                value = row.get("primaryValue")
                if value is None:
                    continue

                obs = {
                    "date": f"{year}-01-01",
                    "value": float(value),
                }

                partner_desc = row.get("partnerDesc", "")
                if partner_desc:
                    obs["partner"] = partner_desc

                cmd_desc = row.get("cmdDesc", "")
                if cmd_desc:
                    obs["commodity"] = cmd_desc

                all_obs.append(obs)

        all_obs.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=title,
            frequency="Annual",
            units="USD",
            notes=f"Reporter: {reporter}, Partner: {partner}, Flow: {flow}, Commodity: {commodity}",
        )
        if all_obs:
            meta.observation_start = all_obs[0]["date"]
            meta.observation_end = all_obs[-1]["date"]

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=all_obs,
            raw_bytes=b"".join(raw_parts),
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []
        for q_id, q_info in COMMON_QUERIES.items():
            if query_lower in q_info["title"].lower() or query_lower in q_id.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=q_id,
                    title=q_info["title"],
                    frequency="Annual",
                    units="USD",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_QUERIES:
            q = COMMON_QUERIES[series_id]
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=q["title"],
                frequency="Annual",
                units="USD",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                reporter="842", year="2022",
                partnerCode="0", flowCode="X", cmdCode="TOTAL",
            )
            rows = data.get("data", [])
            if rows:
                return True, f"Comtrade: key valid ({len(rows)} records)"
            return False, "Comtrade: no data returned"
        except Exception as e:
            return False, f"Comtrade: {e}"
