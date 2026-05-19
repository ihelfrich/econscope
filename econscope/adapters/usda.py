"""USDA NASS adapter — agricultural production, prices, livestock, county-level data.

API docs: https://quickstats.nass.usda.gov/api/
Key required (free registration).

Covers: crop production, acreage, yield, livestock inventory, prices received,
farm economics, county-level agricultural data.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import get_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_QUERIES = {
    "corn_production": {
        "title": "US Corn Production",
        "params": {
            "commodity_desc": "CORN",
            "statisticcat_desc": "PRODUCTION",
            "agg_level_desc": "NATIONAL",
        },
    },
    "soybean_production": {
        "title": "US Soybean Production",
        "params": {
            "commodity_desc": "SOYBEANS",
            "statisticcat_desc": "PRODUCTION",
            "agg_level_desc": "NATIONAL",
        },
    },
    "wheat_production": {
        "title": "US Wheat Production",
        "params": {
            "commodity_desc": "WHEAT",
            "statisticcat_desc": "PRODUCTION",
            "agg_level_desc": "NATIONAL",
        },
    },
    "corn_price": {
        "title": "US Corn Price Received",
        "params": {
            "commodity_desc": "CORN",
            "statisticcat_desc": "PRICE RECEIVED",
            "agg_level_desc": "NATIONAL",
        },
    },
    "cattle_inventory": {
        "title": "US Cattle Inventory",
        "params": {
            "commodity_desc": "CATTLE",
            "statisticcat_desc": "INVENTORY",
            "agg_level_desc": "NATIONAL",
        },
    },
    "milk_production": {
        "title": "US Milk Production",
        "params": {
            "commodity_desc": "MILK",
            "statisticcat_desc": "PRODUCTION",
            "agg_level_desc": "NATIONAL",
        },
    },
    "farm_income": {
        "title": "US Net Farm Income",
        "params": {
            "commodity_desc": "INCOME, NET FARM",
            "agg_level_desc": "NATIONAL",
        },
    },
}


class USDAAdapter(BaseAdapter):
    source_id = "usda"
    source_name = "USDA NASS"
    key_env_var = "USDA_NASS_API_KEY"
    requests_per_minute = 30

    BASE = "https://quickstats.nass.usda.gov/api/api_GET/"

    def __init__(self):
        self.api_key = get_key(self.key_env_var)

    def _get(self, **params) -> tuple[dict, bytes]:
        if not self.api_key:
            raise RuntimeError("USDA_NASS_API_KEY not set. Register at https://quickstats.nass.usda.gov/api/")
        params["key"] = self.api_key
        params["format"] = "JSON"
        url = f"{self.BASE}?{urlencode(params)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from USDA NASS.

        series_id can be:
          - Common name: "corn_production", "cattle_inventory"
          - Custom: pass params via the raw NASS query API
        """
        if series_id in COMMON_QUERIES:
            q = COMMON_QUERIES[series_id]
            params = dict(q["params"])
            title = q["title"]
        else:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Unknown series: '{series_id}'. Use one of: "
                      f"{', '.join(sorted(COMMON_QUERIES)[:5])}...",
            )

        if start:
            params["year__GE"] = start[:4]
        if end:
            params["year__LE"] = end[:4]

        try:
            data, raw = self._get(**params)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        rows = data.get("data", [])
        if not rows:
            error_msg = data.get("error", ["No data"])[0] if "error" in data else "No data returned"
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=error_msg, raw_bytes=raw,
            )

        observations = []
        units = ""
        for row in rows:
            year = row.get("year", "")
            val_str = row.get("Value", "").replace(",", "").strip()
            if not year or not val_str or val_str in ("(D)", "(Z)", "(NA)", "(S)"):
                continue
            try:
                value = float(val_str)
            except (ValueError, TypeError):
                continue

            # Build date from year + reference_period
            ref = row.get("reference_period_desc", "YEAR")
            date_str = self._ref_to_date(year, ref)

            obs = {"date": date_str, "value": value}
            state = row.get("state_name", "")
            if state and state != "US TOTAL":
                obs["geo_name"] = state

            observations.append(obs)
            if not units:
                units = row.get("unit_desc", "")

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=title, frequency="Annual", units=units,
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    @staticmethod
    def _ref_to_date(year: str, ref: str) -> str:
        ref = ref.upper().strip()
        month_map = {
            "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
            "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
            "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
        }
        if ref in month_map:
            return f"{year}-{month_map[ref]}-01"
        return f"{year}-01-01"

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []
        for name, q in COMMON_QUERIES.items():
            if query_lower in q["title"].lower() or query_lower in name:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name, title=q["title"],
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_QUERIES:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=COMMON_QUERIES[series_id]["title"],
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                commodity_desc="CORN", statisticcat_desc="PRODUCTION",
                agg_level_desc="NATIONAL", year="2023",
            )
            rows = data.get("data", [])
            if rows:
                return True, f"USDA NASS: key valid ({len(rows)} records)"
            return False, "USDA NASS: no data returned"
        except Exception as e:
            return False, f"USDA NASS: {e}"
