"""NOAA adapter — climate and weather data (temperature, precipitation, drought).

API docs: https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation

No key needed for NCEI data service. Token needed for CDO API.

Covers: global temperature records, precipitation, drought indices (PDSI),
heating/cooling degree days, sea level, storm events.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

from econscope.config import get_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_DATASETS = {
    "global_temp_monthly": {
        "dataset": "global-summary-of-the-month",
        "title": "Global Monthly Temperature Summary",
        "stations": "USW00094728",  # Central Park, NYC
        "dataTypes": "TAVG,TMAX,TMIN",
        "value_field": "TAVG",
    },
    "us_temp_monthly": {
        "dataset": "climdiv",
        "title": "US Climate Divisions: Temperature",
        "stations": "",
        "dataTypes": "TAVG",
        "value_field": "TAVG",
    },
    "us_precip_monthly": {
        "dataset": "global-summary-of-the-month",
        "title": "US Monthly Precipitation",
        "stations": "USW00094728",
        "dataTypes": "PRCP",
        "value_field": "PRCP",
    },
    "us_drought": {
        "dataset": "global-summary-of-the-month",
        "title": "Palmer Drought Severity Index",
        "stations": "USW00094728",
        "dataTypes": "PSUN",
        "value_field": "PSUN",
    },
}


class NOAAAdapter(BaseAdapter):
    source_id = "noaa"
    source_name = "NOAA"
    key_env_var = ""  # NCEI data service doesn't need a key
    requests_per_minute = 30

    BASE = "https://www.ncei.noaa.gov/access/services/data/v1"

    def __init__(self):
        pass

    def _get(self, **params) -> tuple[list | dict, bytes]:
        url = f"{self.BASE}?{urlencode(params)}"
        req = Request(url)
        req.add_header("Accept", "application/json")
        raw = urlopen(req).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from NOAA NCEI data service.

        series_id can be:
          - Common name: "global_temp_monthly"
          - Custom: "DATASET:STATION:DATATYPES"
        """
        if series_id in COMMON_DATASETS:
            ds = COMMON_DATASETS[series_id]
            dataset = ds["dataset"]
            stations = ds["stations"]
            data_types = ds["dataTypes"]
            value_field = ds["value_field"]
            title = ds["title"]
        else:
            parts = series_id.split(":")
            if len(parts) >= 3:
                dataset, stations, data_types = parts[0], parts[1], parts[2]
                value_field = data_types.split(",")[0]
                title = f"NOAA {dataset}: {data_types}"
            else:
                return PullResult(
                    source=self.source_id, series_id=series_id,
                    metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                    error=f"Unknown series: '{series_id}'. Use a common name or DATASET:STATION:DATATYPES.",
                )

        params = {
            "dataset": dataset,
            "dataTypes": data_types,
            "format": "json",
            "units": "metric",
            "limit": "1000",
        }
        if stations:
            params["stations"] = stations
        if start:
            params["startDate"] = start
        if end:
            params["endDate"] = end
        else:
            params["endDate"] = "2026-12-31"
        if not start:
            params["startDate"] = "2000-01-01"

        try:
            data, raw = self._get(**params)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        rows = data if isinstance(data, list) else []

        observations = []
        for row in rows:
            date_str = row.get("DATE", "")
            if not date_str:
                continue
            # Normalize date
            if len(date_str) == 7:
                date_str = f"{date_str}-01"
            elif len(date_str) == 4:
                date_str = f"{date_str}-01-01"

            raw_val = row.get(value_field, "")
            try:
                value = float(str(raw_val))
            except (ValueError, TypeError):
                continue

            obs = {"date": date_str[:10], "value": value}
            station = row.get("STATION", "")
            if station:
                obs["station"] = station
            name = row.get("NAME", "")
            if name:
                obs["geo_name"] = name

            observations.append(obs)

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=title, notes=f"Dataset: {dataset}, Field: {value_field}",
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
        for name, ds in COMMON_DATASETS.items():
            if query_lower in ds["title"].lower() or query_lower in name:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name, title=ds["title"],
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_DATASETS:
            ds = COMMON_DATASETS[series_id]
            return SeriesMetadata(
                source=self.source_id, series_id=series_id, title=ds["title"],
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                dataset="global-summary-of-the-month",
                stations="USW00094728",
                dataTypes="TAVG",
                startDate="2024-01-01", endDate="2024-03-31",
                format="json", limit="3",
            )
            if isinstance(data, list) and len(data) > 0:
                return True, "NOAA: API accessible (no key needed)"
            return False, "NOAA: no data returned"
        except Exception as e:
            return False, f"NOAA: {e}"
