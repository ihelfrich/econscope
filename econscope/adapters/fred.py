"""FRED adapter — Federal Reserve Economic Data (800K+ time series)."""

import csv
import io
import json
from urllib.parse import urlencode

from econscope.config import get_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_SERIES = {
    "A191RL1Q225SBEA": "Real Gross Domestic Product, percent change from preceding period",
    "PCEPI": "Personal Consumption Expenditures Price Index",
    "PCEPILFE": "Personal Consumption Expenditures Excluding Food and Energy Price Index",
    "DSPIC96": "Real Disposable Personal Income",
    "PSAVERT": "Personal Saving Rate",
    "FEDFUNDS": "Federal Funds Effective Rate",
    "UNRATE": "Unemployment Rate",
    "GDPC1": "Real Gross Domestic Product",
}


class FREDAdapter(BaseAdapter):
    source_id = "fred"
    source_name = "FRED"
    key_env_var = "FRED_API_KEY"
    requests_per_minute = 120

    BASE = "https://api.stlouisfed.org/fred"
    GRAPH_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(self):
        self.api_key = get_key(self.key_env_var)

    def _get(self, endpoint: str, **params) -> tuple[dict, bytes]:
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        url = f"{self.BASE}/{endpoint}?{urlencode(params)}"
        raw = self._http_get(url)
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        if not self.api_key:
            return self._pull_graph_csv(series_id, start=start, end=end)

        try:
            meta = self.get_metadata(series_id)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Failed to fetch metadata: {e}",
            )

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

    def _pull_graph_csv(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Use FRED's public graph CSV export when an API key is unavailable."""
        params = {"id": series_id}
        if start:
            params["cosd"] = start
        if end:
            params["coed"] = end
        url = f"{self.GRAPH_CSV}?{urlencode(params)}"
        try:
            raw = self._http_get(url)
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            observations = []
            for row in reader:
                date = row.get("observation_date") or row.get("DATE") or row.get("date")
                value = row.get(series_id)
                if not date or value in (None, "", "."):
                    continue
                observations.append({"date": date, "value": float(value)})
            if not observations:
                raise ValueError("FRED graph export returned no observations")
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        observations.sort(key=lambda item: item["date"])
        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=COMMON_SERIES.get(series_id, series_id),
                observation_start=observations[0]["date"],
                observation_end=observations[-1]["date"],
                notes="Public FRED graph CSV export; API metadata requires a FRED key.",
            ),
            observations=observations,
            raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        if not self.api_key:
            terms = query.lower().split()
            return [
                SeriesMetadata(source=self.source_id, series_id=sid, title=title)
                for sid, title in COMMON_SERIES.items()
                if all(term in f"{sid} {title}".lower() for term in terms)
            ][:limit]
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
        if not self.api_key:
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=COMMON_SERIES.get(series_id, series_id),
                notes="Public FRED graph CSV export; API metadata requires a FRED key.",
            )
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
