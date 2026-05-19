"""USPTO PatentsView adapter — US patent data (grants, applications, assignees).

API docs: https://patentsview.org/apis/
No key required. REST API with JSON responses.

Covers: patent grants, applications, inventors, assignees, CPC/USPC classes,
citations, locations. Data from 1976 to present.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


class PatentsViewAdapter(BaseAdapter):
    source_id = "patents"
    source_name = "USPTO PatentsView"
    key_env_var = ""
    requests_per_minute = 30

    BASE = "https://search.patentsview.org/api/v1"

    def __init__(self):
        pass

    def _post(self, endpoint: str, body: dict) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}"
        payload = json.dumps(body).encode("utf-8")
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=60).read()
        return json.loads(raw), raw

    def _get(self, endpoint: str) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=60).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull patent data.

        series_id formats:
          - "assignee:{name}" → patents by assignee (e.g., "assignee:Google")
          - "inventor:{name}" → patents by inventor
          - "cpc:{group}" → patents by CPC classification (e.g., "cpc:H01L")
          - "patent:{number}" → specific patent details
          - "search:{query}" → full-text patent search
        """
        parts = series_id.split(":", 1)
        query_type = parts[0]
        param = parts[1] if len(parts) > 1 else ""

        try:
            if query_type == "assignee":
                return self._pull_by_assignee(series_id, param, start, end)
            elif query_type == "inventor":
                return self._pull_by_inventor(series_id, param, start, end)
            elif query_type == "cpc":
                return self._pull_by_cpc(series_id, param, start, end)
            elif query_type == "patent":
                return self._pull_patent(series_id, param)
            elif query_type == "search":
                return self._pull_search(series_id, param, start, end)
            else:
                return self._pull_search(series_id, series_id, start, end)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _pull_by_assignee(self, series_id, name, start, end) -> PullResult:
        """Find patents by assignee organization."""
        q = {"_and": [{"_contains": {"assignees.assignee_organization": name}}]}
        if start:
            q["_and"].append({"_gte": {"patent_date": start}})
        if end:
            q["_and"].append({"_lte": {"patent_date": end}})

        body = {
            "q": q,
            "f": ["patent_number", "patent_date", "patent_title",
                   "patent_num_claims", "patent_type"],
            "o": {"page": 1, "per_page": 100},
            "s": [{"patent_date": "desc"}],
        }

        data, raw = self._post("patents/", body)
        return self._format_patent_results(series_id, f"Assignee: {name}", data, raw)

    def _pull_by_inventor(self, series_id, name, start, end) -> PullResult:
        """Find patents by inventor name."""
        name_parts = name.split()
        q_parts = []
        if len(name_parts) >= 2:
            q_parts.append({"_contains": {"inventors.inventor_name_first": name_parts[0]}})
            q_parts.append({"_contains": {"inventors.inventor_name_last": name_parts[-1]}})
        else:
            q_parts.append({"_contains": {"inventors.inventor_name_last": name}})

        if start:
            q_parts.append({"_gte": {"patent_date": start}})
        if end:
            q_parts.append({"_lte": {"patent_date": end}})

        body = {
            "q": {"_and": q_parts},
            "f": ["patent_number", "patent_date", "patent_title",
                   "patent_num_claims", "patent_type"],
            "o": {"page": 1, "per_page": 100},
            "s": [{"patent_date": "desc"}],
        }

        data, raw = self._post("patents/", body)
        return self._format_patent_results(series_id, f"Inventor: {name}", data, raw)

    def _pull_by_cpc(self, series_id, cpc_group, start, end) -> PullResult:
        """Find patents by CPC classification."""
        q = {"_and": [{"_begins": {"cpcs.cpc_group_id": cpc_group}}]}
        if start:
            q["_and"].append({"_gte": {"patent_date": start}})
        if end:
            q["_and"].append({"_lte": {"patent_date": end}})

        body = {
            "q": q,
            "f": ["patent_number", "patent_date", "patent_title",
                   "patent_num_claims", "patent_type"],
            "o": {"page": 1, "per_page": 100},
            "s": [{"patent_date": "desc"}],
        }

        data, raw = self._post("patents/", body)
        return self._format_patent_results(series_id, f"CPC: {cpc_group}", data, raw)

    def _pull_patent(self, series_id, patent_number) -> PullResult:
        """Pull details for a specific patent."""
        body = {
            "q": {"patent_number": patent_number},
            "f": ["patent_number", "patent_date", "patent_title",
                   "patent_abstract", "patent_num_claims", "patent_type",
                   "patent_num_cited_by_us_patents"],
            "o": {"page": 1, "per_page": 1},
        }

        data, raw = self._post("patents/", body)
        patents = data.get("patents", [])

        if not patents:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Patent {patent_number} not found",
            )

        p = patents[0]
        observations = [
            {"date": k, "value": 0, "property": k, "property_value": str(v)}
            for k, v in p.items() if v is not None
        ]

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=p.get("patent_title", patent_number)[:100],
            notes=f"Patent #{patent_number}, {p.get('patent_type', '')}",
            last_updated=p.get("patent_date", ""),
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_search(self, series_id, query, start, end) -> PullResult:
        """Full-text patent search."""
        q = {"_and": [{"_text_any": {"patent_title": query}}]}
        if start:
            q["_and"].append({"_gte": {"patent_date": start}})
        if end:
            q["_and"].append({"_lte": {"patent_date": end}})

        body = {
            "q": q,
            "f": ["patent_number", "patent_date", "patent_title",
                   "patent_num_claims", "patent_type"],
            "o": {"page": 1, "per_page": 100},
            "s": [{"patent_date": "desc"}],
        }

        data, raw = self._post("patents/", body)
        return self._format_patent_results(series_id, f"Search: {query}", data, raw)

    def _format_patent_results(self, series_id, title, data, raw) -> PullResult:
        """Format patent query results into observations."""
        patents = data.get("patents", [])
        total = data.get("total_patent_count", len(patents))

        observations = []
        for p in patents:
            date = p.get("patent_date", "")
            claims = p.get("patent_num_claims")
            observations.append({
                "date": date,
                "value": float(claims) if claims else 0,
                "patent_number": p.get("patent_number", ""),
                "title": (p.get("patent_title") or "")[:100],
                "type": p.get("patent_type", ""),
            })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Patents: {title}",
            notes=f"{total} total patents",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for patents or suggest query types."""
        results = [
            SeriesMetadata(
                source=self.source_id,
                series_id=f"search:{query}",
                title=f"Patent Title Search: '{query}'",
            ),
            SeriesMetadata(
                source=self.source_id,
                series_id=f"assignee:{query}",
                title=f"Patents by Assignee: '{query}'",
            ),
        ]
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        return SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title="USPTO Patent Data",
        )

    def verify_key(self) -> tuple[bool, str]:
        try:
            body = {
                "q": {"_gte": {"patent_date": "2024-01-01"}},
                "f": ["patent_number"],
                "o": {"page": 1, "per_page": 1},
            }
            data, _ = self._post("patents/", body)
            total = data.get("total_patent_count", 0)
            return True, f"PatentsView: API accessible ({total:,} patents since 2024)"
        except Exception as e:
            return False, f"PatentsView: {e}"
