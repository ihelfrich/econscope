"""Census adapter — U.S. Census Bureau (ACS, population estimates, CBP, decennial).

API docs: https://www.census.gov/data/developers/data-sets.html

Key design notes:
- Base URL: https://api.census.gov/data/
- Response is JSON array of arrays (row 0 = headers, rest = data)
- All values are strings
- Variable names are cryptic (e.g., B01003_001E = total population)
- Geography uses FIPS codes as strings
- 500 req/day without key, unlimited with key
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common Census datasets and variables
COMMON_DATASETS = {
    # ACS 5-Year
    "acs_population": {
        "path": "acs/acs5",
        "title": "Total Population (ACS 5-Year)",
        "variables": ["NAME", "B01003_001E"],
        "geo": "state:*",
        "value_var": "B01003_001E",
        "years": list(range(2009, 2024)),
    },
    "acs_median_income": {
        "path": "acs/acs5",
        "title": "Median Household Income (ACS 5-Year)",
        "variables": ["NAME", "B19013_001E"],
        "geo": "state:*",
        "value_var": "B19013_001E",
        "years": list(range(2009, 2024)),
    },
    "acs_poverty_rate": {
        "path": "acs/acs5",
        "title": "Poverty Status (ACS 5-Year)",
        "variables": ["NAME", "B17001_001E", "B17001_002E"],
        "geo": "state:*",
        "value_var": "B17001_002E",
        "years": list(range(2009, 2024)),
    },
    "acs_education": {
        "path": "acs/acs5",
        "title": "Educational Attainment: Bachelor's Degree or Higher (ACS 5-Year)",
        "variables": ["NAME", "B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E"],
        "geo": "state:*",
        "value_var": "B15003_022E",
        "years": list(range(2009, 2024)),
    },
    "acs_housing_value": {
        "path": "acs/acs5",
        "title": "Median Home Value (ACS 5-Year)",
        "variables": ["NAME", "B25077_001E"],
        "geo": "state:*",
        "value_var": "B25077_001E",
        "years": list(range(2009, 2024)),
    },
    "acs_gini": {
        "path": "acs/acs5",
        "title": "Gini Index of Income Inequality (ACS 5-Year)",
        "variables": ["NAME", "B19083_001E"],
        "geo": "state:*",
        "value_var": "B19083_001E",
        "years": list(range(2009, 2024)),
    },
    # Population Estimates
    "pop_estimates": {
        "path": "pep/population",
        "title": "Population Estimates",
        "variables": ["NAME", "POP"],
        "geo": "state:*",
        "value_var": "POP",
        "years": list(range(2015, 2024)),
    },
    # County Business Patterns
    "cbp_establishments": {
        "path": "cbp",
        "title": "County Business Patterns: Establishments",
        "variables": ["NAME", "ESTAB", "EMP"],
        "geo": "state:*",
        "value_var": "ESTAB",
        "years": list(range(2012, 2023)),
    },
}


class CensusAdapter(BaseAdapter):
    source_id = "census"
    source_name = "Census"
    key_env_var = "CENSUS_API_KEY"
    requests_per_minute = 60

    BASE = "https://api.census.gov/data"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, year: int, dataset_path: str, variables: list[str],
             geo_for: str, geo_in: str = None) -> tuple[list, bytes]:
        """Pull from Census API. Returns (parsed rows, raw bytes)."""
        params = {
            "get": ",".join(variables),
            "for": geo_for,
            "key": self.api_key,
        }
        if geo_in:
            params["in"] = geo_in

        url = f"{self.BASE}/{year}/{dataset_path}?{urlencode(params)}"
        raw = urlopen(url).read()
        data = json.loads(raw)
        return data, raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from Census.

        series_id can be:
          - A common name: "acs_population", "acs_median_income"
          - Custom format: "YEAR:PATH:VARS:GEO" e.g., "2022:acs/acs5:NAME,B01003_001E:state:*"
        """
        if series_id in COMMON_DATASETS:
            ds = COMMON_DATASETS[series_id]
            return self._pull_common(series_id, ds, start, end)

        # Custom format
        parts = series_id.split(":", 3)
        if len(parts) >= 4:
            try:
                year = int(parts[0])
                path = parts[1]
                variables = parts[2].split(",")
                geo = parts[3]
                return self._pull_custom(series_id, year, path, variables, geo)
            except (ValueError, IndexError):
                pass

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
            error=(
                f"Unknown series_id: '{series_id}'. "
                f"Use a common name ({', '.join(sorted(COMMON_DATASETS)[:5])}...) "
                f"or custom format YEAR:PATH:VARS:GEO."
            ),
        )

    def _pull_common(self, series_id: str, ds: dict,
                     start: str = None, end: str = None) -> PullResult:
        """Pull a common dataset across multiple years."""
        start_year = int(start[:4]) if start else min(ds["years"])
        end_year = int(end[:4]) if end else max(ds["years"])
        years = [y for y in ds["years"] if start_year <= y <= end_year]

        all_obs = []
        raw_parts = []

        for year in years:
            try:
                data, raw = self._get(
                    year, ds["path"], ds["variables"], ds["geo"]
                )
                raw_parts.append(raw)
            except Exception:
                continue

            if not data or len(data) < 2:
                continue

            headers = data[0]
            val_idx = headers.index(ds["value_var"]) if ds["value_var"] in headers else None
            name_idx = headers.index("NAME") if "NAME" in headers else None

            if val_idx is None:
                continue

            for row in data[1:]:
                raw_val = row[val_idx]
                try:
                    value = float(str(raw_val).replace(",", ""))
                except (ValueError, TypeError):
                    continue

                obs = {"date": f"{year}-01-01", "value": value}
                if name_idx is not None:
                    obs["geo_name"] = row[name_idx]

                all_obs.append(obs)

        all_obs.sort(key=lambda x: (x["date"], x.get("geo_name", "")))

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=ds["title"],
            frequency="Annual",
            notes=f"Path: {ds['path']}, Variable: {ds['value_var']}",
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

    def _pull_custom(self, series_id: str, year: int, path: str,
                     variables: list[str], geo: str) -> PullResult:
        """Pull a custom Census query for a single year."""
        try:
            data, raw = self._get(year, path, variables, geo)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        if not data or len(data) < 2:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                observations=[],
                raw_bytes=raw,
                error="No data returned",
            )

        headers = data[0]
        # Find first numeric variable
        value_var = None
        for var in variables:
            if var != "NAME":
                value_var = var
                break

        val_idx = headers.index(value_var) if value_var and value_var in headers else 1
        name_idx = headers.index("NAME") if "NAME" in headers else None

        observations = []
        for row in data[1:]:
            try:
                value = float(str(row[val_idx]).replace(",", ""))
            except (ValueError, TypeError):
                continue

            obs = {"date": f"{year}-01-01", "value": value}
            if name_idx is not None:
                obs["geo_name"] = row[name_idx]
            observations.append(obs)

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=f"Census {path} ({year})",
            frequency="Annual",
            notes=f"Variables: {', '.join(variables)}",
        )

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=observations,
            raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []
        for ds_id, ds in COMMON_DATASETS.items():
            if query_lower in ds["title"].lower() or query_lower in ds_id.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=ds_id,
                    title=ds["title"],
                    frequency="Annual",
                    notes=f"Path: {ds['path']}, Variable: {ds['value_var']}",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_DATASETS:
            ds = COMMON_DATASETS[series_id]
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=ds["title"],
                frequency="Annual",
                notes=f"Path: {ds['path']}, Variable: {ds['value_var']}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(2022, "acs/acs5", ["NAME", "B01003_001E"], "state:01")
            if data and len(data) > 1:
                return True, f"Census: key valid (returned {len(data) - 1} rows)"
            return False, "Census: no data returned"
        except Exception as e:
            return False, f"Census: {e}"
