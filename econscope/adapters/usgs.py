"""USGS Earthquake adapter — seismic event data worldwide.

API docs: https://earthquake.usgs.gov/fdsnws/event/1/
No key required. GeoJSON responses.

Covers: earthquakes worldwide, magnitude filtering, geographic bounding,
depth data, real-time and historical seismicity.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Pre-built query profiles
COMMON_QUERIES = {
    "significant": {
        "params": {"minmagnitude": "5.0", "orderby": "time", "limit": "500"},
        "title": "Significant Earthquakes (M5.0+)",
    },
    "major": {
        "params": {"minmagnitude": "6.0", "orderby": "time", "limit": "500"},
        "title": "Major Earthquakes (M6.0+)",
    },
    "great": {
        "params": {"minmagnitude": "7.0", "orderby": "time", "limit": "500"},
        "title": "Great Earthquakes (M7.0+)",
    },
    "us": {
        "params": {
            "minmagnitude": "4.0", "orderby": "time", "limit": "500",
            "minlatitude": "24.5", "maxlatitude": "49.5",
            "minlongitude": "-125", "maxlongitude": "-66.9",
        },
        "title": "US Earthquakes (M4.0+, Contiguous US)",
    },
    "california": {
        "params": {
            "minmagnitude": "3.0", "orderby": "time", "limit": "500",
            "minlatitude": "32", "maxlatitude": "42",
            "minlongitude": "-125", "maxlongitude": "-114",
        },
        "title": "California Earthquakes (M3.0+)",
    },
    "japan": {
        "params": {
            "minmagnitude": "4.0", "orderby": "time", "limit": "500",
            "minlatitude": "24", "maxlatitude": "46",
            "minlongitude": "123", "maxlongitude": "148",
        },
        "title": "Japan Earthquakes (M4.0+)",
    },
    "turkey": {
        "params": {
            "minmagnitude": "4.0", "orderby": "time", "limit": "500",
            "minlatitude": "36", "maxlatitude": "42",
            "minlongitude": "26", "maxlongitude": "45",
        },
        "title": "Turkey Earthquakes (M4.0+)",
    },
}


class USGSAdapter(BaseAdapter):
    source_id = "usgs"
    source_name = "USGS Earthquake"
    key_env_var = ""
    requests_per_minute = 30

    BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    def __init__(self):
        pass

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull earthquake data.

        series_id formats:
          - Common query: "significant", "major", "great", "us", "california"
          - Custom magnitude: "mag:5.5" (global M5.5+)
          - Region with mag: "region:35,-120,38,-115:3.0" (bbox + min magnitude)
        """
        parts = series_id.split(":")
        query_type = parts[0]

        params = {"format": "geojson"}

        if query_type in COMMON_QUERIES:
            params.update(COMMON_QUERIES[query_type]["params"])
            title = COMMON_QUERIES[query_type]["title"]
        elif query_type == "mag":
            min_mag = parts[1] if len(parts) > 1 else "5.0"
            params["minmagnitude"] = min_mag
            params["orderby"] = "time"
            params["limit"] = "500"
            title = f"Global Earthquakes (M{min_mag}+)"
        elif query_type == "region":
            if len(parts) >= 3:
                bbox = parts[1].split(",")
                if len(bbox) == 4:
                    params["minlatitude"] = bbox[0]
                    params["minlongitude"] = bbox[1]
                    params["maxlatitude"] = bbox[2]
                    params["maxlongitude"] = bbox[3]
                params["minmagnitude"] = parts[2]
            params["orderby"] = "time"
            params["limit"] = "500"
            title = f"Regional Earthquakes"
        else:
            params.update(COMMON_QUERIES.get("significant", {}).get("params", {}))
            title = "Significant Earthquakes"

        if start:
            params["starttime"] = start
        if end:
            params["endtime"] = end

        try:
            url = f"{self.BASE}?{urlencode(params)}"
            req = Request(url)
            req.add_header("User-Agent", "econscope/1.0")
            raw = urlopen(req, timeout=30).read()
            data = json.loads(raw)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        features = data.get("features", [])
        observations = []
        for f in features:
            props = f.get("properties", {})
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [0, 0, 0])

            time_ms = props.get("time")
            if not time_ms:
                continue
            from datetime import datetime
            dt = datetime.utcfromtimestamp(time_ms / 1000)
            date_str = dt.strftime("%Y-%m-%d")

            mag = props.get("mag")
            if mag is None:
                continue

            observations.append({
                "date": date_str,
                "value": float(mag),
                "place": props.get("place", ""),
                "depth_km": float(coords[2]) if len(coords) > 2 else 0,
                "longitude": float(coords[0]) if coords else 0,
                "latitude": float(coords[1]) if len(coords) > 1 else 0,
                "type": props.get("type", ""),
                "tsunami": props.get("tsunami", 0),
                "felt": props.get("felt", 0),
            })

        observations.sort(key=lambda x: x["date"])

        meta_count = data.get("metadata", {}).get("count", len(observations))
        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=title,
            frequency="Event", units="Magnitude",
            notes=f"{meta_count} events",
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
                    source=self.source_id, series_id=name,
                    title=q["title"], frequency="Event", units="Magnitude",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_QUERIES:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=COMMON_QUERIES[name]["title"],
                frequency="Event", units="Magnitude",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            result = self.pull_series("great", start="2024-01-01")
            if result.ok:
                return True, f"USGS: API accessible ({result.count} M7.0+ earthquakes since 2024)"
            return False, f"USGS: {result.error}"
        except Exception as e:
            return False, f"USGS: {e}"
