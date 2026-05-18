"""BIS adapter — Bank for International Settlements (cross-border banking, credit, property prices).

API docs: https://stats.bis.org/api-doc/v2/
SDMX REST API, no key required.

Covers: cross-border banking positions, global liquidity, residential property prices,
credit-to-GDP, effective exchange rates, OTC derivatives, international debt securities.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional
from urllib.request import urlopen
from urllib.parse import quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# BIS dataflow IDs and descriptions
COMMON_DATAFLOWS = {
    # Residential property prices
    "property_prices": {
        "dataflow": "WS_SPP",
        "key": "Q.R.{country}",
        "title": "Residential Property Prices",
        "default_country": "US",
    },
    # Credit to GDP
    "credit_to_gdp": {
        "dataflow": "WS_CREDIT_GAP",
        "key": "Q.{country}.G.B.770.A",
        "title": "Credit-to-GDP Gap",
        "default_country": "US",
    },
    # Effective exchange rates (broad, real)
    "reer": {
        "dataflow": "WS_EER",
        "key": "M.R.B.{country}",
        "title": "Real Effective Exchange Rate (Broad)",
        "default_country": "US",
    },
    # Total credit to private non-financial sector
    "total_credit": {
        "dataflow": "WS_TC",
        "key": "Q.{country}.P.A.M.770.A",
        "title": "Total Credit to Private Non-Financial Sector",
        "default_country": "US",
    },
    # Cross-border banking (locational)
    "cross_border_claims": {
        "dataflow": "WS_LBS_D_PUB",
        "key": "Q.S.C.A.TO1.A.5J.A.5A.A.{country}",
        "title": "Locational Banking Statistics: Cross-Border Claims",
        "default_country": "US",
    },
    # Debt securities
    "debt_securities": {
        "dataflow": "WS_DEBT_SEC2_PUB",
        "key": "Q.{country}.1R.2.2B.A.A.A.TO1.A.A.A.A.3P.A",
        "title": "International Debt Securities Outstanding",
        "default_country": "US",
    },
    # Policy rates
    "policy_rates": {
        "dataflow": "WS_CBPOL",
        "key": "D.{country}",
        "title": "Central Bank Policy Rates",
        "default_country": "US",
    },
}


class BISAdapter(BaseAdapter):
    source_id = "bis"
    source_name = "BIS"
    key_env_var = ""  # No key needed
    requests_per_minute = 30

    BASE = "https://stats.bis.org/api/v1"

    def __init__(self):
        pass

    def _get_xml(self, path: str) -> tuple[ET.Element, bytes]:
        url = f"{self.BASE}/{path}"
        raw = urlopen(url).read()
        root = ET.fromstring(raw)
        return root, raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from BIS SDMX API.

        series_id can be:
          - Common name with optional country: "property_prices", "property_prices:GB"
          - Raw: "DATAFLOW/KEY" e.g. "WS_SPP/Q.R.US"
        """
        parts = series_id.split(":")
        common_name = parts[0]
        country = parts[1] if len(parts) > 1 else None

        if common_name in COMMON_DATAFLOWS:
            df = COMMON_DATAFLOWS[common_name]
            c = country or df["default_country"]
            dataflow = df["dataflow"]
            key = df["key"].format(country=c)
            title = f"{df['title']} ({c})"
        elif "/" in series_id:
            # Raw format: DATAFLOW/KEY
            raw_parts = series_id.split("/", 1)
            dataflow = raw_parts[0]
            key = raw_parts[1]
            title = series_id
        else:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Unknown series: '{series_id}'. Use a common name "
                      f"({', '.join(sorted(COMMON_DATAFLOWS)[:5])}...) or DATAFLOW/KEY format.",
            )

        params = "detail=dataonly"
        if start:
            params += f"&startPeriod={start[:7]}"
        if end:
            params += f"&endPeriod={end[:7]}"

        try:
            path = f"data/{quote(dataflow)}/{quote(key, safe='.')}?{params}"
            root, raw = self._get_xml(path)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        observations = self._parse_sdmx_xml(root)
        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=title,
            notes=f"Dataflow: {dataflow}, Key: {key}",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _parse_sdmx_xml(self, root: ET.Element) -> list[dict]:
        """Parse SDMX-ML StructureSpecificData into observations."""
        observations = []
        # Find all Obs elements (any namespace)
        for elem in root.iter():
            if elem.tag.endswith("}Obs") or elem.tag == "Obs":
                period = elem.attrib.get("TIME_PERIOD", "")
                value_str = elem.attrib.get("OBS_VALUE", "")
                if not period or not value_str:
                    continue
                date_str = self._period_to_date(period)
                if not date_str:
                    continue
                try:
                    value = float(value_str)
                except (ValueError, TypeError):
                    continue
                observations.append({"date": date_str, "value": value})
        return observations

    @staticmethod
    def _period_to_date(period: str) -> Optional[str]:
        if not period:
            return None
        if len(period) == 4 and period.isdigit():
            return f"{period}-01-01"
        if len(period) == 7 and period[4] == "-":
            if period[5] == "Q":
                q = int(period[6])
                m = {1: "01", 2: "04", 3: "07", 4: "10"}.get(q, "01")
                return f"{period[:4]}-{m}-01"
            return f"{period}-01"
        if len(period) == 10:
            return period
        return None

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        query_lower = query.lower()
        results = []
        for name, df in COMMON_DATAFLOWS.items():
            if query_lower in df["title"].lower() or query_lower in name:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name,
                    title=df["title"],
                    notes=f"Dataflow: {df['dataflow']}",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_DATAFLOWS:
            df = COMMON_DATAFLOWS[name]
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=df["title"], notes=f"Dataflow: {df['dataflow']}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            root, _ = self._get_xml("data/WS_CBPOL/D.US?detail=dataonly&lastNObservations=1")
            obs = self._parse_sdmx_xml(root)
            if obs:
                return True, f"BIS: API accessible (no key needed, rate={obs[0]['value']}%)"
            return False, "BIS: no data returned"
        except Exception as e:
            return False, f"BIS: {e}"
