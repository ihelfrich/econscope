"""BLS adapter — Bureau of Labor Statistics (CPI, employment, wages, JOLTS, productivity)."""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen, Request

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata

# Common BLS series for quick reference
COMMON_SERIES = {
    "CPI-U All Items": "CUUR0000SA0",
    "CPI-U Food": "CUUR0000SAF1",
    "CPI-U Energy": "CUUR0000SA0E",
    "CPI-U Shelter": "CUUR0000SAH1",
    "CPI-U Medical": "CUUR0000SAM",
    "CPI-U All Items (SA)": "CUSR0000SA0",
    "Total Nonfarm Employment": "CES0000000001",
    "Private Employment": "CES0500000001",
    "Manufacturing Employment": "CES3000000001",
    "Leisure/Hospitality Employment": "CES7000000001",
    "Avg Hourly Earnings Private": "CES0500000003",
    "Avg Weekly Hours Private": "CES0500000002",
    "Unemployment Rate": "LNS14000000",
    "Labor Force Participation": "LNS11300000",
    "Job Openings (JOLTS)": "JTS000000000000000JOL",
    "Quits Rate (JOLTS)": "JTS000000000000000QUR",
    "PPI Final Demand": "WPSFD4",
    "Productivity (Nonfarm Business)": "PRS85006092",
    "Employment Cost Index": "CIU1010000000000A",
}

# BLS period codes to month numbers
PERIOD_MAP = {f"M{str(i).zfill(2)}": i for i in range(1, 13)}
PERIOD_MAP["M13"] = None  # annual average


class BLSAdapter(BaseAdapter):
    source_id = "bls"
    source_name = "BLS"
    key_env_var = "BLS_API_KEY"
    requests_per_minute = 25  # conservative; 500/day with key

    BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _post(self, series_ids: List[str], start_year: int = None,
              end_year: int = None, catalog: bool = False) -> tuple[dict, bytes]:
        payload = {
            "seriesid": series_ids,
            "registrationkey": self.api_key,
        }
        if start_year:
            payload["startyear"] = str(start_year)
        if end_year:
            payload["endyear"] = str(end_year)
        if catalog:
            payload["catalog"] = True

        body = json.dumps(payload).encode()
        req = Request(
            self.BASE,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = urlopen(req).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        from datetime import date as Date
        start_year = int(start[:4]) if start else None
        end_year = int(end[:4]) if end else Date.today().year

        if start_year and not end:
            pass  # end_year already set to current year

        # BLS allows max 20 year span per request
        if start_year and end_year and (end_year - start_year) > 20:
            return self._pull_chunked(series_id, start_year, end_year)

        try:
            data, raw = self._post(
                [series_id], start_year=start_year, end_year=end_year, catalog=True
            )
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        if data.get("status") != "REQUEST_SUCCEEDED":
            msg = "; ".join(data.get("message", []))
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"BLS API error: {msg}",
            )

        series_data = data["Results"]["series"][0]
        meta = self._extract_metadata(series_id, series_data)
        observations = self._extract_observations(series_data)

        # Filter by exact start/end dates if provided
        if start:
            observations = [o for o in observations if o["date"] >= start]
        if end:
            observations = [o for o in observations if o["date"] <= end]

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=observations,
            raw_bytes=raw,
        )

    def _pull_chunked(self, series_id: str, start_year: int, end_year: int) -> PullResult:
        all_obs = []
        raw_parts = []
        meta = SeriesMetadata(source=self.source_id, series_id=series_id)

        year = start_year
        while year <= end_year:
            chunk_end = min(year + 19, end_year)
            try:
                data, raw = self._post(
                    [series_id], start_year=year, end_year=chunk_end, catalog=True
                )
            except Exception as e:
                return PullResult(
                    source=self.source_id, series_id=series_id,
                    metadata=meta, observations=all_obs, error=str(e),
                )

            if data.get("status") == "REQUEST_SUCCEEDED":
                series_data = data["Results"]["series"][0]
                meta = self._extract_metadata(series_id, series_data)
                all_obs.extend(self._extract_observations(series_data))
                raw_parts.append(raw)

            year = chunk_end + 1

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=sorted(all_obs, key=lambda x: x["date"]),
            raw_bytes=b"".join(raw_parts),
        )

    def pull_batch(
        self, series_ids: List[str], start: str = None, end: str = None
    ) -> List[PullResult]:
        """Pull up to 50 series in one request (BLS batch limit)."""
        from datetime import date as Date
        start_year = int(start[:4]) if start else None
        end_year = int(end[:4]) if end else Date.today().year

        results = []
        # BLS allows 50 series per request
        for i in range(0, len(series_ids), 50):
            batch = series_ids[i:i + 50]
            try:
                data, raw = self._post(batch, start_year=start_year, end_year=end_year)
            except Exception as e:
                for sid in batch:
                    results.append(PullResult(
                        source=self.source_id, series_id=sid,
                        metadata=SeriesMetadata(source=self.source_id, series_id=sid),
                        error=str(e),
                    ))
                continue

            if data.get("status") != "REQUEST_SUCCEEDED":
                msg = "; ".join(data.get("message", []))
                for sid in batch:
                    results.append(PullResult(
                        source=self.source_id, series_id=sid,
                        metadata=SeriesMetadata(source=self.source_id, series_id=sid),
                        error=f"BLS API error: {msg}",
                    ))
                continue

            for series_data in data["Results"]["series"]:
                sid = series_data["seriesID"]
                meta = self._extract_metadata(sid, series_data)
                obs = self._extract_observations(series_data)
                results.append(PullResult(
                    source=self.source_id, series_id=sid,
                    metadata=meta, observations=obs, raw_bytes=raw,
                ))

        return results

    def search(self, query: str, limit: int = 20) -> List[SeriesMetadata]:
        # BLS has no search API — match against common series names
        query_lower = query.lower()
        results = []
        for name, sid in COMMON_SERIES.items():
            if query_lower in name.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=sid,
                    title=name,
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        # Pull a tiny window just to get catalog info
        try:
            data, _ = self._post([series_id], start_year=2024, end_year=2024, catalog=True)
            if data.get("status") == "REQUEST_SUCCEEDED":
                series_data = data["Results"]["series"][0]
                return self._extract_metadata(series_id, series_data)
        except Exception:
            pass
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def _extract_metadata(self, series_id: str, series_data: dict) -> SeriesMetadata:
        catalog = series_data.get("catalog", {})
        return SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=catalog.get("series_title", ""),
            frequency=catalog.get("frequency", ""),
            units=catalog.get("unit", ""),
            seasonal_adjustment=catalog.get("seasonally_adjusted", ""),
            notes=catalog.get("survey_name", ""),
        )

    def _extract_observations(self, series_data: dict) -> List[dict]:
        observations = []
        for obs in series_data.get("data", []):
            period = obs.get("period", "")
            month = PERIOD_MAP.get(period)
            if month is None:
                continue
            year = obs["year"]
            date = f"{year}-{str(month).zfill(2)}-01"
            try:
                value = float(obs["value"].replace(",", ""))
            except (ValueError, AttributeError):
                continue
            observations.append({"date": date, "value": value})

        observations.sort(key=lambda x: x["date"])
        return observations

    @staticmethod
    def list_common_series() -> dict:
        return dict(COMMON_SERIES)
