"""DBnomics adapter — aggregator of 80+ statistical providers (ECB, Eurostat, IMF, OECD...).

API docs: https://db.nomics.world/docs/api/

Key design notes:
- No API key required
- Base URL: https://api.db.nomics.world/v22/
- Series ID format: PROVIDER/DATASET/SERIES (e.g., ECB/EXR/M.USD.EUR.SP00.A)
- Extremely rich metadata
- Pagination with limit/offset
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode, quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common DBnomics series
COMMON_SERIES = {
    # ECB
    "ecb_eurusd": (
        "ECB/EXR/M.USD.EUR.SP00.A",
        "EUR/USD Exchange Rate (monthly)",
    ),
    "ecb_hicp": (
        "ECB/ICP/M.U2.N.000000.4.ANR",
        "Euro Area HICP (annual rate of change)",
    ),
    "ecb_policy_rate": (
        "ECB/FM/M.U2.EUR.4F.KR.MRR_FR.LEV",
        "ECB Main Refinancing Rate",
    ),
    # Eurostat
    "eurostat_gdp": (
        "Eurostat/namq_10_gdp/Q.CLV10_MEUR.SA.B1GQ.EA20",
        "Euro Area GDP (chain-linked volumes, SA)",
    ),
    "eurostat_unemployment": (
        "Eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20",
        "Euro Area Unemployment Rate (SA)",
    ),
    # IMF
    "imf_gdp_world": (
        "IMF/WEO:2024-10/USA.NGDP_RPCH",
        "United States Real GDP Growth (IMF WEO)",
    ),
    # OECD
    "oecd_cli": (
        "OECD/MEI_CLI/LOLITOAA.USA.M",
        "OECD Composite Leading Indicator (USA)",
    ),
}


class DBnomicsAdapter(BaseAdapter):
    source_id = "dbnomics"
    source_name = "DBnomics"
    key_env_var = ""  # No key needed
    requests_per_minute = 60

    BASE = "https://api.db.nomics.world/v22"

    def __init__(self):
        pass  # No key required

    def _get(self, endpoint: str, **params) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}"
        if params:
            url += f"?{urlencode(params)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from DBnomics.

        series_id can be:
          - A common name: "ecb_eurusd", "eurostat_gdp"
          - A full DBnomics ID: "ECB/EXR/M.USD.EUR.SP00.A"
        """
        if series_id in COMMON_SERIES:
            dbnomics_id, title = COMMON_SERIES[series_id]
        else:
            dbnomics_id = series_id
            title = series_id

        params = {"observations": "1"}
        if start:
            # DBnomics uses period-based filtering in observations
            pass  # Filter client-side

        try:
            data, raw = self._get(f"series/{quote(dbnomics_id, safe='/')}", **params)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        docs = data.get("series", {}).get("docs", [])
        if not docs:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error="No series found",
                raw_bytes=raw,
            )

        series_doc = docs[0]
        periods = series_doc.get("period", [])
        values = series_doc.get("value", [])

        # Build metadata
        provider = dbnomics_id.split("/")[0] if "/" in dbnomics_id else ""
        series_name = series_doc.get("series_name", title)
        if isinstance(series_name, dict):
            series_name = series_name.get("en", str(series_name))

        freq = series_doc.get("@frequency", "")
        freq_map = {
            "monthly": "Monthly",
            "quarterly": "Quarterly",
            "annual": "Annual",
            "daily": "Daily",
        }
        frequency = freq_map.get(freq.lower(), freq)

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=series_name if isinstance(series_name, str) else str(series_name),
            frequency=frequency,
            units=series_doc.get("unit", ""),
            notes=f"Provider: {provider}, DBnomics ID: {dbnomics_id}",
        )

        observations = []
        for period, value in zip(periods, values):
            if value is None or value == "NA":
                continue

            date_str = self._parse_period(str(period))
            if not date_str:
                continue

            try:
                val = float(value)
            except (ValueError, TypeError):
                continue

            observations.append({"date": date_str, "value": val})

        observations.sort(key=lambda x: x["date"])

        # Filter by date range
        if start:
            observations = [o for o in observations if o["date"] >= start]
        if end:
            observations = [o for o in observations if o["date"] <= end]

        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id,
            series_id=series_id,
            metadata=meta,
            observations=observations,
            raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search DBnomics series."""
        query_lower = query.lower()
        results = []

        # Check common series first
        for sid, (dbnomics_id, title) in COMMON_SERIES.items():
            if query_lower in title.lower() or query_lower in sid.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=sid,
                    title=title,
                    notes=f"DBnomics ID: {dbnomics_id}",
                ))

        if len(results) >= limit:
            return results[:limit]

        # Hit DBnomics search API
        try:
            data, _ = self._get("search", q=query, limit=limit)
            seen = {r.series_id for r in results}
            for item in data.get("results", []):
                sid = item.get("series_code", "")
                full_id = f"{item.get('provider_code', '')}/{item.get('dataset_code', '')}/{sid}"
                if full_id in seen:
                    continue
                name = item.get("series_name", "")
                if isinstance(name, dict):
                    name = name.get("en", str(name))
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=full_id,
                    title=name if isinstance(name, str) else str(name),
                    notes=f"Provider: {item.get('provider_code', '')}",
                ))
        except Exception:
            pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_SERIES:
            dbnomics_id, title = COMMON_SERIES[series_id]
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=title,
                notes=f"DBnomics ID: {dbnomics_id}",
            )

        try:
            dbnomics_id = series_id
            data, _ = self._get(f"series/{quote(dbnomics_id, safe='/')}")
            docs = data.get("series", {}).get("docs", [])
            if docs:
                series_doc = docs[0]
                name = series_doc.get("series_name", "")
                if isinstance(name, dict):
                    name = name.get("en", str(name))
                return SeriesMetadata(
                    source=self.source_id,
                    series_id=series_id,
                    title=name if isinstance(name, str) else str(name),
                    frequency=series_doc.get("@frequency", ""),
                    units=series_doc.get("unit", ""),
                )
        except Exception:
            pass

        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                f"series/{quote('ECB/EXR/M.USD.EUR.SP00.A', safe='/')}",
                observations="1",
            )
            docs = data.get("series", {}).get("docs", [])
            if docs and docs[0].get("period"):
                return True, "DBnomics: API accessible (no key needed)"
            return False, "DBnomics: no data returned"
        except Exception as e:
            return False, f"DBnomics: {e}"

    @staticmethod
    def _parse_period(period: str) -> Optional[str]:
        """Convert DBnomics period to YYYY-MM-DD.

        Handles: "2024", "2024-03", "2024-Q1", "2024-01-15"
        """
        if not period:
            return None

        period = period.strip()

        if len(period) == 4 and period.isdigit():
            return f"{period}-01-01"

        if len(period) == 7 and period[4] == "-":
            if period[5:].isdigit():
                return f"{period}-01"
            # Quarter: "2024-Q1"
            if period[5] == "Q":
                quarter = int(period[6])
                month = {1: "01", 2: "04", 3: "07", 4: "10"}.get(quarter, "01")
                return f"{period[:4]}-{month}-01"

        if len(period) == 10 and period[4] == "-" and period[7] == "-":
            return period

        return None
