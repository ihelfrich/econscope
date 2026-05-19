"""USASpending adapter — federal spending, contracts, grants, loans.

API docs: https://api.usaspending.gov/
No key required. Generous rate limits.

Covers: federal awards, agency budgets, state/county spending, contract recipients,
CFDA programs, NAICS-coded procurement.
"""

from __future__ import annotations

import json
import ssl
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata

# USASpending uses a certificate chain that Python 3.9 doesn't trust by default
_SSL_CTX = ssl.create_default_context()
try:
    import certifi
    _SSL_CTX.load_verify_locations(certifi.where())
except ImportError:
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE


# Pre-built spending queries
COMMON_QUERIES = {
    "total_spending": {
        "endpoint": "spending/over_time/",
        "title": "Total Federal Spending Over Time",
        "body": {"group": "fiscal_year", "filters": {"time_period": []}},
    },
    "agency_spending": {
        "endpoint": "agency/{agency_code}/budgetary_resources/",
        "title": "Agency Budgetary Resources",
        "default_agency": "012",  # USDA
    },
    "state_spending": {
        "endpoint": "recipient/state/{fips}/",
        "title": "State Award Spending",
        "default_fips": "06",  # California
    },
}

# Top federal agencies by code
AGENCIES = {
    "012": "Department of Agriculture",
    "013": "Department of Commerce",
    "014": "Department of the Interior",
    "015": "Department of Justice",
    "016": "Department of Labor",
    "019": "Department of State",
    "020": "Department of the Treasury",
    "021": "Department of the Army",
    "036": "Department of Veterans Affairs",
    "047": "General Services Administration",
    "049": "National Science Foundation",
    "069": "Department of Transportation",
    "070": "Department of Homeland Security",
    "072": "Agency for International Development",
    "075": "Department of Health and Human Services",
    "080": "National Aeronautics and Space Administration",
    "089": "Department of Energy",
    "091": "Department of Education",
    "097": "Department of Defense",
}


class USASpendingAdapter(BaseAdapter):
    source_id = "usaspending"
    source_name = "USASpending"
    key_env_var = ""  # No key needed
    requests_per_minute = 60

    BASE = "https://api.usaspending.gov/api/v2"

    def __init__(self):
        pass

    def _get(self, endpoint: str) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=30, context=_SSL_CTX).read()
        return json.loads(raw), raw

    def _post(self, endpoint: str, body: dict) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}"
        payload = json.dumps(body).encode("utf-8")
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=30, context=_SSL_CTX).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull federal spending data.

        series_id formats:
          - "total_spending" → aggregate over time
          - "agency:{code}" → agency budgetary resources (e.g., "agency:097")
          - "state:{fips}" → state-level spending (e.g., "state:06")
          - "awards:{keyword}" → search awards by keyword
          - "recipient:{name}" → search spending by recipient
        """
        parts = series_id.split(":", 1)
        query_type = parts[0]
        param = parts[1] if len(parts) > 1 else None

        try:
            if query_type == "total_spending":
                return self._pull_total_spending(series_id, start, end)
            elif query_type == "agency":
                return self._pull_agency(series_id, param or "012", start, end)
            elif query_type == "state":
                return self._pull_state(series_id, param or "06")
            elif query_type == "awards":
                return self._pull_awards(series_id, param or "defense", start, end)
            elif query_type == "recipient":
                return self._pull_recipient(series_id, param or "")
            else:
                # Try as total_spending by default
                return self._pull_total_spending(series_id, start, end)
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _pull_total_spending(self, series_id, start, end) -> PullResult:
        """Aggregate federal spending by fiscal year."""
        time_periods = []
        start_fy = int(start[:4]) if start else 2017
        end_fy = int(end[:4]) if end else 2025
        for fy in range(start_fy, end_fy + 1):
            time_periods.append({
                "start_date": f"{fy - 1}-10-01",
                "end_date": f"{fy}-09-30",
            })

        body = {
            "group": "fiscal_year",
            "filters": {
                "time_period": time_periods,
            },
            "subawards": False,
        }
        data, raw = self._post("search/spending_over_time/", body)

        observations = []
        for item in data.get("results", []):
            fy = item.get("time_period", {}).get("fiscal_year")
            amount = item.get("aggregated_amount")
            if fy and amount is not None:
                observations.append({
                    "date": f"{fy}-09-30",
                    "value": float(amount),
                    "fiscal_year": fy,
                })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title="Total Federal Spending by Fiscal Year",
            frequency="Annual", units="USD",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_agency(self, series_id, agency_code, start, end) -> PullResult:
        """Pull agency budgetary resources."""
        agency_name = AGENCIES.get(agency_code, f"Agency {agency_code}")
        data, raw = self._get(f"agency/{agency_code}/budgetary_resources/")

        observations = []
        for item in data.get("agency_budgetary_resources", []):
            fy = item.get("fiscal_year")
            amount = item.get("total_budgetary_resources")
            if fy and amount is not None:
                date_str = f"{fy}-09-30"
                if start and date_str < start:
                    continue
                if end and date_str > end:
                    continue
                observations.append({
                    "date": date_str,
                    "value": float(amount),
                    "fiscal_year": fy,
                    "agency": agency_name,
                })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{agency_name}: Budgetary Resources",
            frequency="Annual", units="USD",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_state(self, series_id, fips) -> PullResult:
        """Pull state-level spending summary."""
        data, raw = self._get(f"recipient/state/{fips}/")

        observations = []
        if isinstance(data, list):
            for item in data:
                fy = item.get("fiscal_year") or item.get("year")
                amount = item.get("amount") or item.get("total")
                if fy and amount is not None:
                    observations.append({
                        "date": f"{fy}-09-30",
                        "value": float(amount),
                    })
        elif isinstance(data, dict):
            # Single year response
            amount = data.get("total") or data.get("amount")
            if amount:
                observations.append({
                    "date": "2024-09-30",
                    "value": float(amount),
                })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"State FIPS {fips}: Federal Award Spending",
            frequency="Annual", units="USD",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_awards(self, series_id, keyword, start, end) -> PullResult:
        """Search federal awards by keyword."""
        time_periods = []
        if start and end:
            time_periods.append({"start_date": start, "end_date": end})
        else:
            time_periods.append({"start_date": "2020-01-01", "end_date": "2025-12-31"})

        body = {
            "filters": {
                "keywords": [keyword],
                "time_period": time_periods,
            },
            "fields": [
                "Award ID", "Recipient Name", "Award Amount",
                "Total Outlays", "Description", "Start Date",
                "Award Type", "Awarding Agency", "Awarding Sub Agency",
            ],
            "page": 1,
            "limit": 100,
            "sort": "Award Amount",
            "order": "desc",
        }
        data, raw = self._post("search/spending_by_award/", body)

        observations = []
        for item in data.get("results", []):
            date = item.get("Start Date", "")
            amount = item.get("Award Amount")
            if amount is not None:
                obs = {
                    "date": date or "unknown",
                    "value": float(amount) if amount else 0,
                    "recipient": item.get("Recipient Name", ""),
                    "description": (item.get("Description") or "")[:200],
                    "award_type": item.get("Award Type", ""),
                    "agency": item.get("Awarding Agency", ""),
                }
                observations.append(obs)

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Awards: '{keyword}'",
            notes=f"{len(observations)} awards found",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_recipient(self, series_id, name) -> PullResult:
        """Search spending by recipient name."""
        body = {
            "keyword": name,
            "limit": 50,
        }
        data, raw = self._post("autocomplete/recipient/", body)

        observations = []
        for i, item in enumerate(data.get("results", [])):
            if isinstance(item, str):
                observations.append({
                    "date": f"match_{i:04d}",
                    "value": 0,
                    "recipient_name": item,
                })
            elif isinstance(item, dict):
                observations.append({
                    "date": f"match_{i:04d}",
                    "value": 0,
                    "recipient_name": item.get("recipient_name", ""),
                })

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"Recipient Search: '{name}'",
            notes=f"{len(observations)} matches",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for spending data.

        Returns a mix of common queries and keyword award searches.
        """
        query_lower = query.lower()
        results = []

        # Check agency names
        for code, name in AGENCIES.items():
            if query_lower in name.lower():
                results.append(SeriesMetadata(
                    source=self.source_id, series_id=f"agency:{code}",
                    title=f"{name}: Budgetary Resources",
                    frequency="Annual", units="USD",
                ))

        # Add total_spending if relevant
        if any(w in query_lower for w in ("total", "spend", "federal", "budget", "all")):
            results.append(SeriesMetadata(
                source=self.source_id, series_id="total_spending",
                title="Total Federal Spending by Fiscal Year",
                frequency="Annual", units="USD",
            ))

        # Add award search suggestion
        results.append(SeriesMetadata(
            source=self.source_id, series_id=f"awards:{query}",
            title=f"Award Search: '{query}'",
            notes="Search federal awards by keyword",
        ))

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        parts = series_id.split(":", 1)
        if parts[0] == "agency" and len(parts) > 1:
            name = AGENCIES.get(parts[1], f"Agency {parts[1]}")
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=f"{name}: Budgetary Resources",
                frequency="Annual", units="USD",
            )
        return SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title="USASpending Federal Data",
        )

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get("references/toptier_agencies/")
            results = data.get("results", [])
            if results:
                # Find a real agency (non-zero budget)
                agency = next((a for a in results if a.get("budget_authority_amount", 0) > 0), results[0])
                name = agency.get("agency_name", "?")
                return True, f"USASpending: API accessible ({len(results)} agencies, e.g. {name})"
            return False, "USASpending: no data returned"
        except Exception as e:
            return False, f"USASpending: {e}"
