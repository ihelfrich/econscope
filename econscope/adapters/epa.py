"""EPA adapter — Environmental Protection Agency (emissions, air quality, TRI, Superfund).

API docs: https://www.epa.gov/enviro/envirofacts-data-service-api

No key required. REST API returns JSON/CSV/XML.

Covers: greenhouse gas emissions, toxic release inventory, air quality,
water permits, Superfund sites, environmental justice scores.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen
from urllib.parse import quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_QUERIES = {
    "ghg_facilities": {
        "table": "PUB_DIM_FACILITY",
        "title": "Greenhouse Gas Reporting: Facility Emissions",
        "value_field": None,  # multiple fields
        "filter": "",
    },
    "ghg_by_state": {
        "table": "PUB_DIM_FACILITY",
        "title": "Greenhouse Gas Facilities by State",
        "value_field": None,
        "filter": "",
    },
    "tri_releases": {
        "table": "TRI_FACILITY",
        "title": "Toxic Release Inventory: Facilities",
        "value_field": None,
        "filter": "",
    },
}


class EPAAdapter(BaseAdapter):
    source_id = "epa"
    source_name = "EPA"
    key_env_var = ""  # No key needed
    requests_per_minute = 20

    BASE = "https://data.epa.gov/efservice"

    def __init__(self):
        pass

    def _get(self, path: str) -> tuple[list | dict, bytes]:
        url = f"{self.BASE}/{path}/JSON"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from EPA Envirofacts.

        series_id format: TABLE/FILTER_FIELD/=VALUE/rows/START:END
        Example: "PUB_DIM_FACILITY/STATE_CODE/=GA/rows/0:100"

        Or common names: "ghg_facilities", "tri_releases"
        """
        if series_id in COMMON_QUERIES:
            q = COMMON_QUERIES[series_id]
            path = f"{q['table']}/rows/0:500"
            title = q["title"]
        else:
            path = series_id
            title = series_id

        try:
            data, raw = self._get(path)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        rows = data if isinstance(data, list) else []

        observations = []
        for i, row in enumerate(rows):
            # EPA data is tabular, not always time series
            # Try to find a year/date field
            date_str = None
            for key in ("REPORTING_YEAR", "YEAR", "RY", "TRI_REPORTING_YEAR"):
                if key in row:
                    yr = str(row[key])
                    if yr.isdigit() and len(yr) == 4:
                        date_str = f"{yr}-01-01"
                        break

            if not date_str:
                date_str = f"2024-01-01"  # fallback for cross-sectional data

            # Try to find a numeric value field
            value = None
            for key in ("TOTAL_REPORTED_DIRECT_EMISSIONS", "GHG_QUANTITY",
                        "TOTAL_RELEASES", "ON_SITE_RELEASE_TOTAL", "EMISSION"):
                if key in row and row[key] is not None:
                    try:
                        value = float(row[key])
                        break
                    except (ValueError, TypeError):
                        continue

            if value is None:
                value = float(i)  # row index as fallback for non-numeric tables

            obs = {"date": date_str, "value": value}

            # Add geographic info
            for geo_key in ("STATE_CODE", "STATE_NAME", "STATE"):
                if geo_key in row:
                    obs["geo_name"] = str(row[geo_key])
                    break
            for name_key in ("FACILITY_NAME", "FAC_NAME"):
                if name_key in row:
                    obs["facility"] = str(row[name_key])
                    break

            observations.append(obs)

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=title, notes=f"EPA Envirofacts: {path}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

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
            data, _ = self._get("PUB_DIM_FACILITY/STATE_CODE/=GA/rows/0:3")
            if isinstance(data, list) and len(data) > 0:
                return True, "EPA: API accessible (no key needed)"
            return False, "EPA: no data returned"
        except Exception as e:
            return False, f"EPA: {e}"
