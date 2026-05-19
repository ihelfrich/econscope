"""CourtListener adapter — federal court opinions, PACER data, judges, oral arguments.

API docs: https://www.courtlistener.com/api/rest/v4/
Key required (free). Rate limit: 5,000 requests/hour authenticated.

Covers: SCOTUS, circuit courts, district courts, bankruptcy courts, state courts.
Full opinion text, citation networks, judge profiles, oral argument audio.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from econscope.config import get_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Federal courts by short name
COURTS = {
    "scotus": "Supreme Court of the United States",
    "ca1": "First Circuit", "ca2": "Second Circuit", "ca3": "Third Circuit",
    "ca4": "Fourth Circuit", "ca5": "Fifth Circuit", "ca6": "Sixth Circuit",
    "ca7": "Seventh Circuit", "ca8": "Eighth Circuit", "ca9": "Ninth Circuit",
    "ca10": "Tenth Circuit", "ca11": "Eleventh Circuit", "cadc": "D.C. Circuit",
    "cafc": "Federal Circuit",
}


class CourtListenerAdapter(BaseAdapter):
    source_id = "courtlistener"
    source_name = "CourtListener"
    key_env_var = "COURTLISTENER_API_TOKEN"
    requests_per_minute = 60  # 5K/hour ≈ 83/min, stay conservative

    BASE = "https://www.courtlistener.com/api/rest/v4"

    def __init__(self):
        self.api_key = get_key(self.key_env_var)

    def _get(self, endpoint: str, **params) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}/"
        if params:
            url += f"?{urlencode(params)}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0 (economic research platform)")
        req.add_header("Accept", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Token {self.api_key}")
        raw = urlopen(req, timeout=30).read()
        return json.loads(raw), raw

    def _search(self, endpoint: str, **params) -> tuple[dict, bytes]:
        """Search endpoint uses a different base."""
        url = f"https://www.courtlistener.com/api/rest/v4/search/"
        params["type"] = endpoint
        if params:
            url += f"?{urlencode(params)}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Token {self.api_key}")
        raw = urlopen(req, timeout=30).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull court data.

        series_id formats:
          - "opinions:{query}" → search court opinions by text
          - "opinions:{query}:{court}" → filter by court (e.g., "opinions:antitrust:scotus")
          - "dockets:{query}" → search docket entries
          - "judges:{name}" → search judges by name
          - "opinion:{id}" → specific opinion by cluster ID
          - "citations:{id}" → citation network for an opinion
        """
        parts = series_id.split(":", 2)
        query_type = parts[0]

        try:
            if query_type == "opinions":
                query = parts[1] if len(parts) > 1 else ""
                court = parts[2] if len(parts) > 2 else None
                return self._pull_opinions(series_id, query, court, start, end)
            elif query_type == "dockets":
                query = parts[1] if len(parts) > 1 else ""
                return self._pull_dockets(series_id, query, start, end)
            elif query_type == "judges":
                name = parts[1] if len(parts) > 1 else ""
                return self._pull_judges(series_id, name)
            elif query_type == "opinion":
                opinion_id = parts[1] if len(parts) > 1 else ""
                return self._pull_opinion_detail(series_id, opinion_id)
            elif query_type == "citations":
                opinion_id = parts[1] if len(parts) > 1 else ""
                return self._pull_citations(series_id, opinion_id)
            else:
                # Default to opinion search
                return self._pull_opinions(series_id, series_id, None, start, end)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _pull_opinions(self, series_id, query, court, start, end) -> PullResult:
        """Search court opinions."""
        params = {"q": query, "order_by": "dateFiled desc"}
        if court:
            params["court"] = court
        if start:
            params["filed_after"] = start
        if end:
            params["filed_before"] = end

        data, raw = self._search("o", **params)

        observations = []
        for item in data.get("results", []):
            date_filed = item.get("dateFiled", "")
            observations.append({
                "date": date_filed,
                "value": item.get("citeCount", 0),
                "case_name": (item.get("caseName") or "")[:100],
                "court": item.get("court", ""),
                "citation": (item.get("citation", [None]) or [None])[0] if isinstance(item.get("citation"), list) else item.get("citation", ""),
                "cluster_id": item.get("cluster_id", ""),
                "status": item.get("status", ""),
                "judge": item.get("judge", ""),
            })

        observations.sort(key=lambda x: x["date"])
        count_total = data.get("count", len(observations))

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Court Opinions: '{query}'" + (f" ({court})" if court else ""),
            frequency="Event",
            notes=f"{count_total} total results",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_dockets(self, series_id, query, start, end) -> PullResult:
        """Search dockets."""
        params = {"q": query, "order_by": "dateFiled desc"}
        if start:
            params["filed_after"] = start
        if end:
            params["filed_before"] = end

        data, raw = self._search("r", **params)

        observations = []
        for item in data.get("results", []):
            date_filed = item.get("dateFiled", "")
            observations.append({
                "date": date_filed,
                "value": 0,
                "case_name": (item.get("caseName") or "")[:100],
                "court": item.get("court", ""),
                "docket_number": item.get("docketNumber", ""),
                "docket_id": item.get("docket_id", ""),
            })

        observations.sort(key=lambda x: x["date"])
        count_total = data.get("count", len(observations))

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Dockets: '{query}'",
            frequency="Event",
            notes=f"{count_total} total results",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_judges(self, series_id, name) -> PullResult:
        """Search judges by name."""
        data, raw = self._get("people", q=name)

        observations = []
        for item in data.get("results", []):
            full_name = f"{item.get('name_first', '')} {item.get('name_last', '')}".strip()
            observations.append({
                "date": item.get("date_dob", "") or "unknown",
                "value": 0,
                "name": full_name,
                "person_id": item.get("id", ""),
                "gender": item.get("gender", ""),
                "race": ", ".join(item.get("race", [])) if item.get("race") else "",
            })

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Judges: '{name}'",
            notes=f"{len(observations)} results",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_opinion_detail(self, series_id, cluster_id) -> PullResult:
        """Pull a specific opinion cluster."""
        data, raw = self._get(f"clusters/{cluster_id}")

        case_name = data.get("case_name", "")
        observations = [
            {"date": k, "value": 0, "property": k, "property_value": str(v)[:200]}
            for k, v in data.items()
            if v is not None and k not in ("resource_uri",)
        ]

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=case_name[:100] or f"Opinion Cluster {cluster_id}",
            last_updated=data.get("date_modified", ""),
            notes=f"Filed: {data.get('date_filed', '')}, Court: {data.get('docket', {}).get('court', '') if isinstance(data.get('docket'), dict) else ''}",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_citations(self, series_id, cluster_id) -> PullResult:
        """Pull citations for an opinion."""
        data, raw = self._get("citations", citing_opinion__cluster_id=cluster_id)

        observations = []
        for item in data.get("results", []):
            observations.append({
                "date": "citation",
                "value": item.get("depth", 0),
                "cited_opinion": item.get("cited_opinion", ""),
                "citing_opinion": item.get("citing_opinion", ""),
            })

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Citations for Cluster {cluster_id}",
            notes=f"{len(observations)} citations",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search across opinions, dockets, and judges."""
        results = [
            SeriesMetadata(
                source=self.source_id,
                series_id=f"opinions:{query}",
                title=f"Court Opinions: '{query}'",
                frequency="Event",
            ),
            SeriesMetadata(
                source=self.source_id,
                series_id=f"dockets:{query}",
                title=f"Docket Search: '{query}'",
                frequency="Event",
            ),
        ]

        # Also try to search opinions and return actual results
        try:
            data, _ = self._search("o", q=query, order_by="dateFiled desc")
            for item in data.get("results", [])[:limit - 2]:
                case_name = (item.get("caseName") or "Unknown")[:60]
                court = item.get("court", "")
                cluster_id = item.get("cluster_id", "")
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"opinion:{cluster_id}",
                    title=f"{case_name} ({court})",
                    frequency="Event",
                    notes=f"Filed: {item.get('dateFiled', '')}",
                ))
        except Exception:
            pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        return SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title="CourtListener Legal Data",
        )

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._search(
                "o", q="securities fraud", order_by="dateFiled desc",
            )
            count = data.get("count", 0)
            results = data.get("results", [])
            if results:
                latest = results[0]
                return True, f"CourtListener: API accessible ({count:,} securities fraud opinions, latest: {latest.get('dateFiled', '?')})"
            return False, "CourtListener: no results returned"
        except Exception as e:
            return False, f"CourtListener: {e}"
