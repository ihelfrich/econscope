"""OECD adapter — OECD data via SDMX 3.0 REST API.

API: https://sdmx.oecd.org/public/rest/
Data explorer: https://data-explorer.oecd.org/

No key required. Covers: GDP, trade, employment, education, health, tax,
inequality, productivity, housing across 38+ OECD members.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Verified working OECD SDMX 3.0 dataflows
# Format: agency,dsd@df,version/key
COMMON_SERIES = {
    "gdp": {
        "agency": "OECD.SDD.NAD",
        "dataflow": "DSD_NAMAIN10@DF_TABLE1",
        "version": "2.0",
        "key": "A.{country}.S1.S1.B1GQ._Z._Z._Z.XDC.V.N.T0101",
        "title": "GDP (Annual, Current Prices, National Currency)",
        "default_country": "USA",
    },
    "gdp_real": {
        "agency": "OECD.SDD.NAD",
        "dataflow": "DSD_NAMAIN10@DF_TABLE1",
        "version": "2.0",
        "key": "Q.{country}.S1.S1.B1GQ._Z._Z._Z.XDC.L.N.T0101",
        "title": "GDP (Quarterly, Constant Prices, National Currency)",
        "default_country": "USA",
    },
    "unemployment": {
        "agency": "OECD.SDD.TPS",
        "dataflow": "DSD_LFS@DF_IALFS_INDIC",
        "version": "1.0",
        "key": "{country}.UNE_LF_M.PT_LF_SUB._Z.Y._T.Y_GE15._Z.M",
        "title": "Unemployment Rate (Monthly, SA, 15+)",
        "default_country": "USA",
    },
    "cpi": {
        "agency": "OECD.SDD.TPS",
        "dataflow": "DSD_PRICES@DF_PRICES_ALL",
        "version": "1.0",
        "key": "{country}.M.N.CPI.PA._T.N.GY",
        "title": "CPI Inflation (Monthly, Year-over-Year)",
        "default_country": "USA",
    },
    "cpi_index": {
        "agency": "OECD.SDD.TPS",
        "dataflow": "DSD_PRICES@DF_PRICES_ALL",
        "version": "1.0",
        "key": "{country}.M.N.CPI.IX._T.N.N",
        "title": "CPI Index Level (Monthly)",
        "default_country": "USA",
    },
}

# ISO-3 country codes for common OECD members
COUNTRIES = {
    "US": "USA", "USA": "USA", "GB": "GBR", "UK": "GBR", "GBR": "GBR",
    "DE": "DEU", "DEU": "DEU", "FR": "FRA", "FRA": "FRA",
    "JP": "JPN", "JPN": "JPN", "CA": "CAN", "CAN": "CAN",
    "AU": "AUS", "AUS": "AUS", "IT": "ITA", "ITA": "ITA",
    "ES": "ESP", "ESP": "ESP", "KR": "KOR", "KOR": "KOR",
    "MX": "MEX", "MEX": "MEX", "NL": "NLD", "NLD": "NLD",
    "CH": "CHE", "CHE": "CHE", "SE": "SWE", "SWE": "SWE",
    "OECD": "OECD",
}


class OECDAdapter(BaseAdapter):
    source_id = "oecd"
    source_name = "OECD"
    key_env_var = ""
    requests_per_minute = 20

    BASE = "https://sdmx.oecd.org/public/rest"

    def __init__(self):
        pass

    def _get(self, path: str) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{path}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/vnd.sdmx.data+json;version=2.0.0")
        raw = urlopen(req, timeout=60).read()
        return json.loads(raw), raw

    def _resolve_country(self, code: str) -> str:
        """Resolve 2-letter or common code to ISO-3."""
        return COUNTRIES.get(code.upper(), code.upper())

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull OECD data.

        series_id formats:
          - Common name with optional country: "gdp", "gdp:DEU", "cpi:JPN"
          - Raw: "AGENCY,DSD@DF,VERSION/KEY"
        """
        parts = series_id.split(":")
        name = parts[0]
        country = parts[1] if len(parts) > 1 else None

        if name in COMMON_SERIES:
            ds = COMMON_SERIES[name]
            c = self._resolve_country(country) if country else ds["default_country"]
            agency = ds["agency"]
            dataflow = ds["dataflow"]
            version = ds["version"]
            key = ds["key"].format(country=c)
            title = f"{ds['title']} ({c})"
        else:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Unknown series: '{series_id}'. Use a common name "
                      f"({', '.join(sorted(COMMON_SERIES)[:5])}...) or specify country with colon.",
            )

        params = ["dimensionAtObservation=AllDimensions", "format=jsondata"]
        if start:
            params.append(f"startPeriod={start[:7]}")
        if end:
            params.append(f"endPeriod={end[:7]}")

        param_str = "&".join(params)

        try:
            path = f"data/{agency},{dataflow},{version}/{key}?{param_str}"
            data, raw = self._get(path)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        observations = self._parse_sdmx_json(data)
        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=title,
            notes=f"Dataflow: {dataflow}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _parse_sdmx_json(self, data: dict) -> list[dict]:
        """Parse SDMX-JSON 2.0 (dimensionAtObservation=AllDimensions) format.

        OECD nests the structure under data.structures[0] (plural),
        and datasets under data.dataSets or data.structures[0].dataSets.
        """
        observations = []

        inner = data.get("data", data)

        # Find structure — OECD uses structures (plural, list)
        structures = inner.get("structures", [])
        structure = structures[0] if structures else inner.get("structure", {})
        dims = structure.get("dimensions", {})

        # Find datasets
        datasets = inner.get("dataSets", [])
        if not datasets:
            datasets = structure.get("dataSets", [])
        if not datasets:
            return observations

        # With AllDimensions, all dims (including TIME_PERIOD) are in observation
        obs_dims = dims.get("observation", [])
        time_dim_idx = None
        time_values = {}
        for i, dim in enumerate(obs_dims):
            if dim.get("id") == "TIME_PERIOD":
                time_dim_idx = i
                for j, val in enumerate(dim.get("values", [])):
                    time_values[j] = val.get("id", val.get("name", ""))
                break

        if time_dim_idx is None:
            return observations

        ds = datasets[0]

        # observations: { "0:0:0:...:time_idx": [value, ...], ... }
        obs_data = ds.get("observations", {})
        for key_str, val_arr in obs_data.items():
            indices = key_str.split(":")
            if time_dim_idx < len(indices):
                time_idx = int(indices[time_dim_idx])
                period = time_values.get(time_idx, "")
                if not period or not val_arr:
                    continue
                try:
                    value = float(val_arr[0]) if val_arr[0] is not None else None
                except (ValueError, TypeError, IndexError):
                    continue
                if value is not None:
                    observations.append({
                        "date": self._period_to_date(period),
                        "value": value,
                    })

        return observations

    @staticmethod
    def _period_to_date(period: str) -> str:
        """Convert OECD period string to YYYY-MM-DD."""
        p = period.strip()
        if len(p) == 4 and p.isdigit():
            return f"{p}-01-01"
        if "-Q" in p:
            year = p[:4]
            q = p.split("Q")[-1]
            month = {"1": "01", "2": "04", "3": "07", "4": "10"}.get(q, "01")
            return f"{year}-{month}-01"
        if "-" in p and len(p) == 7:
            return f"{p}-01"
        if len(p) == 10:
            return p
        return p

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []

        for name, ds in COMMON_SERIES.items():
            if query_lower in ds["title"].lower() or query_lower in name:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name,
                    title=ds["title"],
                    notes=f"Dataflow: {ds['dataflow']}",
                ))

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_SERIES:
            ds = COMMON_SERIES[name]
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=ds["title"], notes=f"Dataflow: {ds['dataflow']}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            result = self.pull_series("unemployment:USA")
            if result.ok and result.count > 0:
                latest = result.observations[-1]
                return True, f"OECD: API accessible (US unemployment {latest['value']}%, {latest['date']})"
            return False, f"OECD: {result.error or 'no data returned'}"
        except Exception as e:
            return False, f"OECD: {e}"
