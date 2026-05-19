"""Eurostat adapter — EU statistical data via JSON API.

API docs: https://ec.europa.eu/eurostat/databrowser/
JSON API: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/

No key required. Covers: GDP, unemployment, inflation, trade, demographics,
government finance, energy, transport, agriculture across EU member states.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common Eurostat dataset codes with useful defaults
COMMON_DATASETS = {
    "gdp": {
        "code": "namq_10_gdp",
        "title": "GDP and Main Components (Quarterly)",
        "params": {"na_item": "B1GQ", "s_adj": "SCA", "unit": "CLV10_MEUR"},
        "default_geo": "EU27_2020",
    },
    "unemployment": {
        "code": "une_rt_m",
        "title": "Unemployment Rate (Monthly)",
        "params": {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"},
        "default_geo": "EU27_2020",
    },
    "hicp": {
        "code": "prc_hicp_manr",
        "title": "HICP Inflation (Annual Rate, Monthly)",
        "params": {"coicop": "CP00", "unit": "RCH_A"},
        "default_geo": "EU27_2020",
    },
    "trade_balance": {
        "code": "ext_lt_maineu",
        "title": "EU Trade Balance with Main Partners",
        "params": {"stk_flow": "BAL", "sitc06": "TOTAL"},
        "default_geo": "EU27_2020",
    },
    "government_debt": {
        "code": "gov_10dd_edpt1",
        "title": "Government Debt (% of GDP)",
        "params": {"na_item": "GD", "sector": "S13", "unit": "PC_GDP"},
        "default_geo": "EU27_2020",
    },
    "population": {
        "code": "demo_pjan",
        "title": "Population on 1 January",
        "params": {"age": "TOTAL", "sex": "T"},
        "default_geo": "EU27_2020",
    },
    "industrial_production": {
        "code": "sts_inpr_m",
        "title": "Industrial Production Index (Monthly)",
        "params": {"s_adj": "SCA", "nace_r2": "B-D", "unit": "I15"},
        "default_geo": "EU27_2020",
    },
    "energy_prices": {
        "code": "nrg_pc_203",
        "title": "Electricity Prices (Household Consumers)",
        "params": {"tax": "I_TAX", "currency": "EUR", "consom": "4161903"},
        "default_geo": "EU27_2020",
    },
}


class EurostatAdapter(BaseAdapter):
    source_id = "eurostat"
    source_name = "Eurostat"
    key_env_var = ""
    requests_per_minute = 30

    BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

    def __init__(self):
        pass

    def _get(self, dataset_code: str, **params) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{quote(dataset_code)}"
        if params:
            url += f"?{urlencode(params, doseq=True)}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=60).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull Eurostat data.

        series_id formats:
          - Common name with optional geo: "gdp", "gdp:DE", "unemployment:ES"
          - Raw dataset code with geo: "namq_10_gdp:DE"
          - Full: "dataset_code:geo:extra_param=value"
        """
        parts = series_id.split(":")
        name = parts[0]
        geo = parts[1] if len(parts) > 1 else None

        if name in COMMON_DATASETS:
            ds = COMMON_DATASETS[name]
            code = ds["code"]
            extra_params = dict(ds["params"])
            geo = geo or ds["default_geo"]
            title = ds["title"]
        else:
            code = name
            extra_params = {}
            geo = geo or "EU27_2020"
            title = f"Eurostat: {code}"

        extra_params["geo"] = geo
        extra_params["format"] = "JSON"
        if start:
            extra_params["sinceTimePeriod"] = start[:7] if len(start) > 7 else start[:4]
        if end:
            extra_params["untilTimePeriod"] = end[:7] if len(end) > 7 else end[:4]

        try:
            data, raw = self._get(code, **extra_params)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        observations = self._parse_json_stat(data)
        observations.sort(key=lambda x: x["date"])

        geo_label = self._resolve_geo_label(data, geo)
        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title} ({geo_label})",
            notes=f"Dataset: {code}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _parse_json_stat(self, data: dict) -> list[dict]:
        """Parse Eurostat JSON-stat format into observations."""
        observations = []

        # Get time dimension
        dimension = data.get("dimension", {})
        time_dim = dimension.get("time", {})
        time_category = time_dim.get("category", {})
        time_index = time_category.get("index", {})
        time_label = time_category.get("label", {})

        # Values are indexed by flat position
        values = data.get("value", {})
        size = data.get("size", [])

        if not time_index or not values:
            return observations

        # Build index mapping: the time dimension position → value index
        # For single-geo, single-indicator queries, it's usually 1:1
        dim_ids = list(data.get("id", []))
        if "time" not in dim_ids:
            return observations

        time_dim_idx = dim_ids.index("time")
        time_size = size[time_dim_idx] if time_dim_idx < len(size) else 0

        # Calculate stride for the time dimension
        stride = 1
        for i in range(time_dim_idx + 1, len(size)):
            stride *= size[i]

        # Calculate offset (product of all dimensions before time that are index 0)
        # For a simple query with 1 value per other dimension, offset = 0
        for time_key, time_pos in time_index.items():
            flat_idx = time_pos * stride
            val = values.get(str(flat_idx))
            if val is None:
                continue

            period = time_label.get(time_key, time_key)
            date_str = self._period_to_date(period)
            observations.append({"date": date_str, "value": float(val)})

        return observations

    @staticmethod
    def _period_to_date(period: str) -> str:
        """Convert Eurostat period to YYYY-MM-DD."""
        p = period.strip()
        if len(p) == 4 and p.isdigit():
            return f"{p}-01-01"
        if "Q" in p:
            year = p[:4]
            q = p.split("Q")[-1].strip()
            month = {"1": "01", "2": "04", "3": "07", "4": "10"}.get(q, "01")
            return f"{year}-{month}-01"
        if "M" in p:
            parts = p.split("M")
            if len(parts) == 2:
                return f"{parts[0]}-{parts[1].zfill(2)}-01"
        if "-" in p and len(p) == 7:
            return f"{p}-01"
        return p

    @staticmethod
    def _resolve_geo_label(data: dict, geo_code: str) -> str:
        """Get human-readable label for a geo code."""
        geo_dim = data.get("dimension", {}).get("geo", {})
        labels = geo_dim.get("category", {}).get("label", {})
        return labels.get(geo_code, geo_code)

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []

        for name, ds in COMMON_DATASETS.items():
            if query_lower in ds["title"].lower() or query_lower in name or query_lower in ds["code"]:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name,
                    title=ds["title"],
                    notes=f"Dataset: {ds['code']}",
                ))

        # Also try searching the Eurostat TOC API
        if len(results) < limit:
            try:
                url = f"https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc?lang=en"
                req = Request(url)
                req.add_header("User-Agent", "econscope/1.0")
                raw = urlopen(req, timeout=15).read()
                toc = json.loads(raw)
                seen = {r.series_id for r in results}
                for item in toc.get("items", [])[:500]:
                    code = item.get("code", "")
                    title = item.get("title", "")
                    if code in seen:
                        continue
                    if query_lower in title.lower() or query_lower in code.lower():
                        results.append(SeriesMetadata(
                            source=self.source_id, series_id=code,
                            title=title[:100],
                        ))
                        if len(results) >= limit:
                            break
            except Exception:
                pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_DATASETS:
            ds = COMMON_DATASETS[name]
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=ds["title"], notes=f"Dataset: {ds['code']}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                "une_rt_m",
                geo="EU27_2020", s_adj="SA", age="TOTAL", sex="T",
                unit="PC_ACT", format="JSON",
                sinceTimePeriod="2024-01",
            )
            obs = self._parse_json_stat(data)
            if obs:
                latest = obs[-1]
                return True, f"Eurostat: API accessible (EU unemployment {latest['value']}%, {latest['date']})"
            return False, "Eurostat: no data returned"
        except Exception as e:
            return False, f"Eurostat: {e}"
