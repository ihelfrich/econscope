"""FRED adapter — Federal Reserve Economic Data (800K+ time series)."""

import json
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


class FREDAdapter(BaseAdapter):
    source_id = "fred"
    source_name = "FRED"
    key_env_var = "FRED_API_KEY"
    requests_per_minute = 120

    BASE = "https://api.stlouisfed.org/fred"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, endpoint: str, **params) -> tuple[dict, bytes]:
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        url = f"{self.BASE}/{endpoint}?{urlencode(params)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        meta = self.get_metadata(series_id)

        params = {"series_id": series_id}
        if start:
            params["observation_start"] = start
        if end:
            params["observation_end"] = end

        try:
            data, raw = self._get("series/observations", **params)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=meta,
                error=str(e),
            )

        observations = []
        for obs in data.get("observations", []):
            val = obs.get("value", ".")
            if val == ".":
                continue
            observations.append({
                "date": obs["date"],
                "value": float(val),
            })

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=observations,
            raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        data, _ = self._get(
            "series/search",
            search_text=query,
            limit=limit,
            order_by="search_rank",
        )
        results = []
        for s in data.get("seriess", []):
            results.append(self._parse_series_meta(s))
        return results

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        data, _ = self._get("series", series_id=series_id)
        series_list = data.get("seriess", [])
        if not series_list:
            return SeriesMetadata(source=self.source_id, series_id=series_id)
        return self._parse_series_meta(series_list[0])

    def get_categories(self, series_id: str) -> list[dict]:
        data, _ = self._get("series/categories", series_id=series_id)
        return data.get("categories", [])

    def get_release(self, series_id: str) -> dict:
        data, _ = self._get("series/release", series_id=series_id)
        releases = data.get("releases", [])
        return releases[0] if releases else {}

    def browse_category(self, category_id: int = 0) -> dict:
        if category_id == 0:
            data, _ = self._get("category", category_id=0)
        else:
            data, _ = self._get("category/children", category_id=category_id)
        return data

    def list_category_series(
        self, category_id: int, limit: int = 100
    ) -> list[SeriesMetadata]:
        data, _ = self._get(
            "category/series", category_id=category_id, limit=limit
        )
        return [self._parse_series_meta(s) for s in data.get("seriess", [])]

    def _parse_series_meta(self, s: dict) -> SeriesMetadata:
        return SeriesMetadata(
            source=self.source_id,
            series_id=s.get("id", ""),
            title=s.get("title", ""),
            frequency=s.get("frequency", ""),
            units=s.get("units", ""),
            seasonal_adjustment=s.get("seasonal_adjustment", ""),
            last_updated=s.get("last_updated", ""),
            observation_start=s.get("observation_start", ""),
            observation_end=s.get("observation_end", ""),
            notes=s.get("notes", ""),
        )
