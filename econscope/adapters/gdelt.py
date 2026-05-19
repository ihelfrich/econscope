"""GDELT adapter — Global Database of Events, Language, and Tone.

API docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
No key required. BigQuery access also available.

Covers: global events (protests, conflicts, diplomacy, disasters), news volume,
tone/sentiment, geographic hotspots, real-time event monitoring.
The GDELT DOC API searches the entire global news landscape.
The GDELT GEO API provides geographic event hotspots.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# GDELT event categories (CAMEO root codes)
EVENT_CATEGORIES = {
    "01": "Make public statement",
    "02": "Appeal",
    "03": "Express intent to cooperate",
    "04": "Consult",
    "05": "Engage in diplomatic cooperation",
    "06": "Engage in material cooperation",
    "07": "Provide aid",
    "08": "Yield",
    "09": "Investigate",
    "10": "Demand",
    "11": "Disapprove",
    "12": "Reject",
    "13": "Threaten",
    "14": "Protest",
    "15": "Exhibit military posture",
    "16": "Reduce relations",
    "17": "Coerce",
    "18": "Assault",
    "19": "Fight",
    "20": "Engage in unconventional mass violence",
}

# Pre-built queries
COMMON_QUERIES = {
    "conflict": {
        "query": "conflict OR war OR military OR attack",
        "title": "Global Conflict Events",
    },
    "trade_war": {
        "query": "tariff OR trade war OR sanctions OR embargo",
        "title": "Trade War / Sanctions Events",
    },
    "financial_crisis": {
        "query": "financial crisis OR bank failure OR recession OR default",
        "title": "Financial Crisis Events",
    },
    "climate": {
        "query": "climate change OR drought OR flood OR wildfire OR hurricane",
        "title": "Climate / Natural Disaster Events",
    },
    "protest": {
        "query": "protest OR demonstration OR strike OR riot",
        "title": "Global Protest Events",
    },
    "election": {
        "query": "election OR vote OR referendum OR ballot",
        "title": "Election / Voting Events",
    },
    "energy": {
        "query": "oil price OR OPEC OR natural gas OR energy crisis OR pipeline",
        "title": "Energy Market Events",
    },
    "tech": {
        "query": "artificial intelligence OR AI regulation OR tech antitrust OR data privacy",
        "title": "Technology / AI Events",
    },
}


class GDELTAdapter(BaseAdapter):
    source_id = "gdelt"
    source_name = "GDELT"
    key_env_var = ""
    requests_per_minute = 30

    DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
    GEO_API = "https://api.gdeltproject.org/api/v2/geo/geo"
    TV_API = "https://api.gdeltproject.org/api/v2/tv/tv"

    def __init__(self):
        pass

    def _get_doc(self, **params) -> tuple[dict | list, bytes]:
        params["format"] = "json"
        url = f"{self.DOC_API}?{urlencode(params)}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        raw = urlopen(req, timeout=60).read()
        return json.loads(raw), raw

    def _get_geo(self, **params) -> tuple[dict | list, bytes]:
        params["format"] = "GeoJSON"
        url = f"{self.GEO_API}?{urlencode(params)}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        raw = urlopen(req, timeout=60).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull GDELT event/news data.

        series_id formats:
          - Common query name: "conflict", "trade_war", "financial_crisis"
          - "timeline:{query}" → article volume over time
          - "tone:{query}" → average tone/sentiment over time
          - "geo:{query}" → geographic hotspots
          - "articles:{query}" → recent article list
          - "tv:{query}" → TV news mentions
        """
        parts = series_id.split(":", 1)
        query_type = parts[0]
        query_text = parts[1] if len(parts) > 1 else None

        # Check common queries
        if query_type in COMMON_QUERIES and query_text is None:
            query_text = COMMON_QUERIES[query_type]["query"]
            title_prefix = COMMON_QUERIES[query_type]["title"]
        else:
            title_prefix = query_text or query_type

        # Default to timeline mode for common queries
        if query_type in COMMON_QUERIES:
            return self._pull_timeline(series_id, query_text, title_prefix, start, end)

        try:
            if query_type == "timeline":
                return self._pull_timeline(series_id, query_text or "", title_prefix, start, end)
            elif query_type == "tone":
                return self._pull_tone(series_id, query_text or "", title_prefix, start, end)
            elif query_type == "geo":
                return self._pull_geo(series_id, query_text or "", title_prefix)
            elif query_type == "articles":
                return self._pull_articles(series_id, query_text or "", title_prefix, start, end)
            else:
                return self._pull_timeline(series_id, query_type, title_prefix, start, end)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _pull_timeline(self, series_id, query, title, start, end) -> PullResult:
        """Pull article volume timeline."""
        params = {
            "query": query,
            "mode": "TimelineVol",
            "TIMESPAN": "12m",
        }
        if start:
            params["STARTDATETIME"] = start.replace("-", "") + "000000"
        if end:
            params["ENDDATETIME"] = end.replace("-", "") + "235959"

        data, raw = self._get_doc(**params)

        observations = []
        timeline = data.get("timeline", [])
        if timeline and isinstance(timeline, list):
            for series in timeline:
                for point in series.get("data", []):
                    date_str = point.get("date", "")
                    if date_str and len(date_str) >= 8:
                        formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                        observations.append({
                            "date": formatted,
                            "value": float(point.get("value", 0)),
                        })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title}: Article Volume",
            frequency="Daily", units="Article count",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_tone(self, series_id, query, title, start, end) -> PullResult:
        """Pull average tone/sentiment timeline."""
        params = {
            "query": query,
            "mode": "TimelineTone",
            "TIMESPAN": "12m",
        }
        if start:
            params["STARTDATETIME"] = start.replace("-", "") + "000000"
        if end:
            params["ENDDATETIME"] = end.replace("-", "") + "235959"

        data, raw = self._get_doc(**params)

        observations = []
        timeline = data.get("timeline", [])
        if timeline and isinstance(timeline, list):
            for series in timeline:
                for point in series.get("data", []):
                    date_str = point.get("date", "")
                    if date_str and len(date_str) >= 8:
                        formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                        observations.append({
                            "date": formatted,
                            "value": float(point.get("value", 0)),
                        })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title}: Sentiment Tone",
            frequency="Daily", units="Tone (-100 to +100)",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_geo(self, series_id, query, title) -> PullResult:
        """Pull geographic event hotspots."""
        params = {"query": query}

        data, raw = self._get_geo(**params)

        observations = []
        features = data.get("features", [])
        for f in features:
            props = f.get("properties", {})
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [0, 0])
            observations.append({
                "date": props.get("date", ""),
                "value": float(props.get("count", 0)),
                "name": props.get("name", ""),
                "type": props.get("type", ""),
                "longitude": float(coords[0]) if coords else 0,
                "latitude": float(coords[1]) if len(coords) > 1 else 0,
                "url": props.get("url", ""),
            })

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title}: Geographic Hotspots",
            notes=f"{len(observations)} locations",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_articles(self, series_id, query, title, start, end) -> PullResult:
        """Pull recent articles matching query."""
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": "100",
            "sort": "DateDesc",
        }
        if start:
            params["STARTDATETIME"] = start.replace("-", "") + "000000"
        if end:
            params["ENDDATETIME"] = end.replace("-", "") + "235959"

        data, raw = self._get_doc(**params)

        observations = []
        articles = data.get("articles", [])
        for art in articles:
            date_str = art.get("seendate", "")
            if date_str and len(date_str) >= 8:
                formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            else:
                formatted = date_str

            observations.append({
                "date": formatted,
                "value": float(art.get("tone", 0)),
                "title": (art.get("title") or "")[:100],
                "source": art.get("domain", ""),
                "language": art.get("language", ""),
                "url": art.get("url", ""),
            })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title}: Articles",
            notes=f"{len(observations)} articles",
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
            if query_lower in q["title"].lower() or query_lower in name or query_lower in q["query"].lower():
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name,
                    title=q["title"], frequency="Daily",
                ))

        # Always add custom query options
        results.extend([
            SeriesMetadata(
                source=self.source_id,
                series_id=f"timeline:{query}",
                title=f"Article Volume: '{query}'",
                frequency="Daily",
            ),
            SeriesMetadata(
                source=self.source_id,
                series_id=f"tone:{query}",
                title=f"Sentiment Tone: '{query}'",
                frequency="Daily",
            ),
            SeriesMetadata(
                source=self.source_id,
                series_id=f"articles:{query}",
                title=f"Recent Articles: '{query}'",
            ),
        ])

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_QUERIES:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=COMMON_QUERIES[name]["title"], frequency="Daily",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            result = self.pull_series("timeline:economic recession")
            if result.ok and result.count > 0:
                return True, f"GDELT: API accessible ({result.count} daily data points)"
            return False, f"GDELT: {result.error or 'no data returned'}"
        except Exception as e:
            return False, f"GDELT: {e}"
