"""FAOSTAT adapter — global agricultural production, trade, land use, food prices.

API docs: https://www.fao.org/faostat/en/#data
Bulk API: https://fenixservices.fao.org/faostat/api/v1/

No key required. 245 countries, data since 1961.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


COMMON_DOMAINS = {
    "crop_production": {
        "domain": "QCL",
        "title": "Crops and Livestock Products",
        "element": "5510",  # Production quantity
        "item": "15",       # Wheat
    },
    "food_trade": {
        "domain": "TP",
        "title": "Trade: Crops and Livestock Products",
        "element": "5910",  # Export quantity
        "item": "15",
    },
    "land_use": {
        "domain": "RL",
        "title": "Land Use",
        "element": "5110",  # Area
        "item": "6600",     # Agricultural land
    },
    "food_prices": {
        "domain": "PP",
        "title": "Producer Prices",
        "element": "5532",  # Producer price (USD/tonne)
        "item": "15",
    },
    "fertilizer": {
        "domain": "RFN",
        "title": "Fertilizers by Nutrient",
        "element": "5157",  # Agricultural use
        "item": "3102",     # Nitrogen
    },
    "food_balance": {
        "domain": "FBS",
        "title": "Food Balances",
        "element": "664",   # Food supply (kcal/capita/day)
        "item": "2501",     # Population
    },
    "emissions": {
        "domain": "GT",
        "title": "Emissions: Agriculture Total",
        "element": "7231",  # Emissions (CO2eq)
        "item": "1711",     # Agriculture total
    },
}


class FAOAdapter(BaseAdapter):
    source_id = "fao"
    source_name = "FAOSTAT"
    key_env_var = ""  # No key needed
    requests_per_minute = 20

    BASE = "https://fenixservices.fao.org/faostat/api/v1/en/data"

    def __init__(self):
        pass

    def _get(self, domain: str, **params) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{domain}"
        if params:
            url += f"?{urlencode(params, doseq=True)}"
        raw = urlopen(url).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull from FAOSTAT.

        series_id can be:
          - Common name: "crop_production", "food_prices"
          - Common name with country: "crop_production:USA"
          - Raw domain code: "QCL" (returns default query)
        """
        parts = series_id.split(":")
        name = parts[0]
        country = parts[1] if len(parts) > 1 else None

        if name in COMMON_DOMAINS:
            d = COMMON_DOMAINS[name]
            domain = d["domain"]
            title = d["title"]
            element = d["element"]
            item = d["item"]
        else:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"Unknown series: '{series_id}'. Use: "
                      f"{', '.join(sorted(COMMON_DOMAINS)[:5])}...",
            )

        params = {
            "element": element,
            "item": item,
            "output_type": "objects",
        }
        if country:
            params["area"] = country
        else:
            params["area"] = "5000"  # World

        start_year = int(start[:4]) if start else 2000
        end_year = int(end[:4]) if end else 2024
        params["year"] = ",".join(str(y) for y in range(start_year, end_year + 1))

        try:
            data, raw = self._get(domain, **params)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        rows = data.get("data", [])

        observations = []
        units = ""
        for row in rows:
            year = row.get("Year")
            value = row.get("Value")
            if year is None or value is None:
                continue

            try:
                val = float(value)
            except (ValueError, TypeError):
                continue

            obs = {"date": f"{year}-01-01", "value": val}
            area = row.get("Area", "")
            if area:
                obs["geo_name"] = area

            observations.append(obs)
            if not units:
                units = row.get("Unit", "")

        observations.sort(key=lambda x: (x["date"], x.get("geo_name", "")))

        country_label = country or "World"
        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{title} ({country_label})",
            frequency="Annual", units=units,
            notes=f"Domain: {domain}, Element: {element}, Item: {item}",
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
        for name, d in COMMON_DOMAINS.items():
            if query_lower in d["title"].lower() or query_lower in name:
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=name, title=d["title"],
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        name = series_id.split(":")[0]
        if name in COMMON_DOMAINS:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=COMMON_DOMAINS[name]["title"],
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("QCL", element="5510", item="15",
                                area="5000", year="2022",
                                output_type="objects")
            rows = data.get("data", [])
            if rows:
                return True, f"FAOSTAT: API accessible ({len(rows)} records)"
            return False, "FAOSTAT: no data returned"
        except Exception as e:
            return False, f"FAOSTAT: {e}"
