"""World Bank adapter — World Development Indicators and other WB datasets.

API docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392

Key design notes:
- No API key required
- Base URL: https://api.worldbank.org/v2/
- format=json required (default is XML)
- Response: [metadata_page, [data_rows]]
- Pagination: page, per_page (max 32767)
- 15,000+ indicators across 200+ countries
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode, quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common World Bank indicators
COMMON_INDICATORS = {
    # GDP and national accounts
    "NY.GDP.MKTP.CD": "GDP (current US$)",
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "NY.GDP.PCAP.CD": "GDP per capita (current US$)",
    "NY.GDP.PCAP.PP.CD": "GDP per capita, PPP (current intl $)",
    "NE.GDI.FTOT.ZS": "Gross fixed capital formation (% of GDP)",
    # Trade
    "NE.EXP.GNFS.ZS": "Exports of goods and services (% of GDP)",
    "NE.IMP.GNFS.ZS": "Imports of goods and services (% of GDP)",
    "TG.VAL.TOTL.GD.ZS": "Merchandise trade (% of GDP)",
    "BN.CAB.XOKA.GD.ZS": "Current account balance (% of GDP)",
    # Population and labor
    "SP.POP.TOTL": "Population, total",
    "SP.POP.GROW": "Population growth (annual %)",
    "SP.URB.TOTL.IN.ZS": "Urban population (% of total)",
    "SL.UEM.TOTL.ZS": "Unemployment, total (% of labor force)",
    "SL.TLF.CACT.ZS": "Labor force participation rate, total (%)",
    # Prices and finance
    "FP.CPI.TOTL.ZG": "Inflation, consumer prices (annual %)",
    "FR.INR.RINR": "Real interest rate (%)",
    "PA.NUS.FCRF": "Official exchange rate (LCU per US$)",
    "FM.LBL.BMNY.GD.ZS": "Broad money (% of GDP)",
    # Poverty and inequality
    "SI.POV.DDAY": "Poverty headcount ratio at $2.15/day (%)",
    "SI.POV.GINI": "Gini index",
    "SI.DST.10TH.10": "Income share held by highest 10%",
    # Health and education
    "SP.DYN.LE00.IN": "Life expectancy at birth, total (years)",
    "SE.ADT.LITR.ZS": "Literacy rate, adult total (%)",
    "SH.XPD.CHEX.GD.ZS": "Current health expenditure (% of GDP)",
    # Infrastructure and technology
    "IT.NET.USER.ZS": "Individuals using the Internet (% of population)",
    "EG.USE.PCAP.KG.OE": "Energy use (kg of oil equivalent per capita)",
    "EN.ATM.CO2E.PC": "CO2 emissions (metric tons per capita)",
}


class WorldBankAdapter(BaseAdapter):
    source_id = "worldbank"
    source_name = "World Bank"
    key_env_var = ""  # No key needed
    requests_per_minute = 60

    BASE = "https://api.worldbank.org/v2"

    def __init__(self):
        pass  # No key required

    def _get(self, endpoint: str, **params) -> tuple[list, bytes]:
        params["format"] = "json"
        params["per_page"] = params.get("per_page", "10000")
        url = f"{self.BASE}/{endpoint}?{urlencode(params)}"
        raw = urlopen(url).read()
        data = json.loads(raw)
        return data, raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from World Bank.

        series_id format: INDICATOR or COUNTRY:INDICATOR
          Examples:
            NY.GDP.MKTP.CD                → All countries, GDP current US$
            USA:NY.GDP.MKTP.CD            → United States only
            USA;GBR;DEU:NY.GDP.MKTP.CD    → Multiple countries
        """
        parts = series_id.split(":", 1)
        if len(parts) == 2:
            country = parts[0]
            indicator = parts[1]
        else:
            indicator = parts[0]
            country = "all"

        params = {}
        if start:
            params["date"] = f"{start[:4]}:{end[:4] if end else '2026'}"
        elif end:
            params["date"] = f"1960:{end[:4]}"

        try:
            endpoint = f"country/{quote(country)}/indicator/{quote(indicator)}"
            data, raw = self._get(endpoint, **params)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        # WB response: [page_info, data_rows] or error dict
        if not isinstance(data, list) or len(data) < 2 or data[1] is None:
            error_msg = "No data returned"
            if isinstance(data, list) and data[0]:
                msg = data[0].get("message", [])
                if msg:
                    error_msg = str(msg)
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=error_msg,
                raw_bytes=raw,
            )

        rows = data[1]
        title = indicator
        if indicator in COMMON_INDICATORS:
            title = COMMON_INDICATORS[indicator]
        elif rows:
            ind_info = rows[0].get("indicator", {})
            title = ind_info.get("value", indicator)

        observations = []
        for row in rows:
            if row.get("value") is None:
                continue

            year = row.get("date", "")
            try:
                value = float(row["value"])
            except (ValueError, TypeError):
                continue

            obs = {"date": f"{year}-01-01", "value": value}

            country_info = row.get("country", {})
            if country_info:
                obs["geo_name"] = country_info.get("value", "")
                obs["geo_code"] = country_info.get("id", "")

            observations.append(obs)

        observations.sort(key=lambda x: (x["date"], x.get("geo_name", "")))

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=title,
            frequency="Annual",
            notes=f"Indicator: {indicator}, Country: {country}",
        )
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
        """Search World Bank indicators. First checks common list, then hits API."""
        query_lower = query.lower()
        results = []

        # Check common indicators first
        for ind_id, title in COMMON_INDICATORS.items():
            if query_lower in title.lower() or query_lower in ind_id.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=ind_id,
                    title=title,
                ))

        if len(results) >= limit:
            return results[:limit]

        # Hit the API search
        try:
            data, _ = self._get(
                f"indicator",
                search=query,
                per_page=str(limit),
            )
            if isinstance(data, list) and len(data) > 1 and data[1]:
                seen = {r.series_id for r in results}
                for item in data[1]:
                    ind_id = item.get("id", "")
                    if ind_id in seen:
                        continue
                    results.append(SeriesMetadata(
                        source=self.source_id,
                        series_id=ind_id,
                        title=item.get("name", ""),
                        notes=item.get("sourceNote", "")[:200],
                    ))
        except Exception:
            pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        parts = series_id.split(":", 1)
        indicator = parts[-1]

        if indicator in COMMON_INDICATORS:
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=COMMON_INDICATORS[indicator],
                frequency="Annual",
            )

        # Hit API for full metadata
        try:
            data, _ = self._get(f"indicator/{quote(indicator)}")
            if isinstance(data, list) and len(data) > 1 and data[1]:
                item = data[1][0]
                return SeriesMetadata(
                    source=self.source_id,
                    series_id=series_id,
                    title=item.get("name", ""),
                    frequency="Annual",
                    units=item.get("unit", ""),
                    notes=item.get("sourceNote", "")[:200],
                )
        except Exception:
            pass

        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("country/USA/indicator/NY.GDP.MKTP.CD",
                                date="2022:2022")
            if isinstance(data, list) and len(data) > 1 and data[1]:
                return True, "World Bank: API accessible (no key needed)"
            return False, "World Bank: no data returned"
        except Exception as e:
            return False, f"World Bank: {e}"
