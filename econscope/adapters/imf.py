"""IMF adapter — International Monetary Fund (IFS, BOP, WEO, DOTS).

SDMX REST API, no key required.
Base URL: https://sdmxcentral.imf.org/ws/public/sdmxapi/rest/

Covers: International Financial Statistics, Balance of Payments,
Direction of Trade, World Economic Outlook forecasts, currency reserves.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_SERIES = {
    # IFS — International Financial Statistics
    "ifs_cpi": {
        "dataflow": "STA,IFS,1.0",
        "key": "M.{country}.PCPI_IX",
        "title": "Consumer Price Index (IFS)",
        "default_country": "US",
    },
    "ifs_gdp": {
        "dataflow": "STA,IFS,1.0",
        "key": "Q.{country}.NGDP_SA_XDC",
        "title": "GDP, Nominal, SA, Domestic Currency (IFS)",
        "default_country": "US",
    },
    "ifs_reserves": {
        "dataflow": "STA,IFS,1.0",
        "key": "M.{country}.RAFA_USD",
        "title": "Total Reserves (IFS)",
        "default_country": "US",
    },
    "ifs_interest_rate": {
        "dataflow": "STA,IFS,1.0",
        "key": "M.{country}.FPOLM_PA",
        "title": "Monetary Policy Rate (IFS)",
        "default_country": "US",
    },
    # BOP — Balance of Payments
    "bop_current_account": {
        "dataflow": "STA,BOP,6.0",
        "key": "Q.{country}.BCA_BP6_USD",
        "title": "Current Account Balance (BOP6)",
        "default_country": "US",
    },
    # DOTS — Direction of Trade
    "dots_exports": {
        "dataflow": "STA,DOT,6.0",
        "key": "M.{country}.TMG_CIF_USD.W00",
        "title": "Total Imports, CIF (DOTS)",
        "default_country": "US",
    },
}


class IMFAdapter(BaseAdapter):
    source_id = "imf"
    source_name = "IMF"
    key_env_var = ""  # No key needed
    requests_per_minute = 30

    BASE = "https://sdmxcentral.imf.org/ws/public/sdmxapi/rest"

    def __init__(self):
        pass

    def _get(self, path: str) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{path}"
        req = Request(url)
        req.add_header("Accept", "application/vnd.sdmx.data+json;version=2.0.0")
        raw = urlopen(req).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from IMF SDMX.

        series_id can be:
          - Common name: "ifs_cpi", "ifs_cpi:GB", "bop_current_account:JP"
          - Raw: "DATAFLOW/KEY"
        """
        parts = series_id.split(":")
        common_name = parts[0]
        country = parts[1] if len(parts) > 1 else None

        if common_name in COMMON_SERIES:
            s = COMMON_SERIES[common_name]
            c = country or s["default_country"]
            dataflow = s["dataflow"]
            key = s["key"].format(country=c)
            title = f"{s['title']} ({c})"
        elif "/" in series_id:
            raw_parts = series_id.split("/", 1)
            dataflow = raw_parts[0]
            key = raw_parts[1]
            title = series_id
        else:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Unknown series: '{series_id}'. Use a common name or DATAFLOW/KEY.",
            )

        params = "detail=dataonly"
        if start:
            params += f"&startPeriod={start[:7]}"
        if end:
            params += f"&endPeriod={end[:7]}"

        try:
            path = f"data/{dataflow}/{key}?{params}"
            data, raw = self._get(path)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        observations = self._parse_sdmx(data)
        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=title, notes=f"Dataflow: {dataflow}, Key: {key}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _parse_sdmx(self, data: dict) -> list[dict]:
        """Parse SDMX-JSON v2 response."""
        observations = []

        datasets = data.get("dataSets", [])
        if not datasets:
            return observations

        structure = data.get("structure", {})
        dims = structure.get("dimensions", {})
        obs_dims = dims.get("observation", [])

        time_dim = None
        for d in obs_dims:
            if d.get("id") in ("TIME_PERIOD", "TIME"):
                time_dim = d
                break

        if not time_dim:
            return observations

        time_values = {str(i): v.get("id", "") for i, v in enumerate(time_dim.get("values", []))}

        ds = datasets[0]
        series_map = ds.get("series", {})
        if not series_map:
            obs_map = ds.get("observations", {})
            for idx, val_list in obs_map.items():
                period = time_values.get(str(idx), "")
                date_str = self._period_to_date(period)
                if date_str and val_list and val_list[0] is not None:
                    observations.append({"date": date_str, "value": float(val_list[0])})
        else:
            for series_key, series_data in series_map.items():
                obs_map = series_data.get("observations", {})
                for idx, val_list in obs_map.items():
                    period = time_values.get(str(idx), "")
                    date_str = self._period_to_date(period)
                    if date_str and val_list and val_list[0] is not None:
                        observations.append({"date": date_str, "value": float(val_list[0])})

        return observations

    @staticmethod
    def _period_to_date(period: str) -> Optional[str]:
        if not period:
            return None
        if len(period) == 4 and period.isdigit():
            return f"{period}-01-01"
        if len(period) == 7 and "-Q" in period:
            year = period[:4]
            q = int(period[6])
            m = {1: "01", 2: "04", 3: "07", 4: "10"}.get(q, "01")
            return f"{year}-{m}-01"
        if len(period) == 7 and period[4] == "-":
            return f"{period}-01"
        if len(period) == 10:
            return period
        return None

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []
        for name, s in COMMON_SERIES.items():
            if query_lower in s["title"].lower() or query_lower in name:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name,
                    title=s["title"], notes=f"Dataflow: {s['dataflow']}",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_SERIES:
            s = COMMON_SERIES[name]
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=s["title"], notes=f"Dataflow: {s['dataflow']}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("data/STA,IFS,1.0/M.US.PCPI_IX?detail=dataonly&lastNObservations=1")
            if data.get("dataSets"):
                return True, "IMF: API accessible (no key needed)"
            return False, "IMF: no data returned"
        except Exception as e:
            return False, f"IMF: {e}"
