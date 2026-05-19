"""FDIC BankFind adapter — US bank financial data, failures, structure.

API docs: https://banks.data.fdic.gov/docs/
No key required. REST API with JSON responses.

Covers: bank financials (Call Reports), bank structure, historical failures,
branch locations, holding companies.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common financial metrics from Call Reports
FINANCIALS_FIELDS = {
    "ASSET": "Total Assets",
    "DEP": "Total Deposits",
    "DEPDOM": "Domestic Deposits",
    "NETINC": "Net Income",
    "NETINCQ": "Net Income (Quarterly)",
    "NIMY": "Net Interest Margin",
    "ROA": "Return on Assets",
    "ROE": "Return on Equity",
    "LNLSNET": "Net Loans and Leases",
    "SC": "Total Securities",
    "EQTOT": "Total Equity Capital",
    "INTINC": "Total Interest Income",
    "ELNANTR": "Provision for Loan Losses",
    "NCLNLS": "Noncurrent Loans",
    "P3ASSET": "Past-Due 30-89 / Total Assets",
    "P9ASSET": "Past-Due 90+ / Total Assets",
    "OFFDOM": "Off-Balance Sheet Items",
}

# Interesting series
COMMON_SERIES = {
    "failures": {
        "endpoint": "failures",
        "title": "FDIC Bank Failures",
    },
    "financials": {
        "endpoint": "financials",
        "title": "Bank Financial Reports (Call Reports)",
    },
    "institutions": {
        "endpoint": "institutions",
        "title": "FDIC-Insured Institutions",
    },
    "history": {
        "endpoint": "history",
        "title": "Institution History Events",
    },
}


class FDICAdapter(BaseAdapter):
    source_id = "fdic"
    source_name = "FDIC BankFind"
    key_env_var = ""
    requests_per_minute = 60

    BASE = "https://banks.data.fdic.gov/api"

    def __init__(self):
        pass

    def _get(self, endpoint: str, **params) -> tuple[dict, bytes]:
        url = f"{self.BASE}/{endpoint}"
        if params:
            url += f"?{urlencode(params)}"
        req = Request(url)
        req.add_header("User-Agent", "econscope/1.0")
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=30).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull FDIC bank data.

        series_id formats:
          - "failures" → historical bank failures
          - "financials:{cert}" → financials for a specific bank by FDIC cert number
          - "financials:{cert}:{field}" → specific metric (e.g., "financials:628:ASSET")
          - "industry:{field}" → industry aggregate for a field
          - "institution:{cert}" → institution details
          - "search:{name}" → search institutions by name
        """
        parts = series_id.split(":")
        query_type = parts[0]

        try:
            if query_type == "failures":
                return self._pull_failures(series_id, start, end)
            elif query_type == "financials":
                cert = parts[1] if len(parts) > 1 else None
                field = parts[2] if len(parts) > 2 else "ASSET"
                if cert:
                    return self._pull_financials(series_id, cert, field, start, end)
                return self._pull_industry(series_id, field, start, end)
            elif query_type == "industry":
                field = parts[1] if len(parts) > 1 else "ASSET"
                return self._pull_industry(series_id, field, start, end)
            elif query_type == "institution":
                cert = parts[1] if len(parts) > 1 else None
                return self._pull_institution(series_id, cert)
            elif query_type == "search":
                name = ":".join(parts[1:]) if len(parts) > 1 else ""
                results = self.search(name, limit=50)
                observations = [
                    {"date": f"match_{i:04d}", "value": 0,
                     "cert": r.series_id.split(":")[-1] if ":" in r.series_id else "",
                     "name": r.title}
                    for i, r in enumerate(results)
                ]
                meta = SeriesMetadata(
                    source=self.source_id, series_id=series_id,
                    title=f"Search: {name}", notes=f"{len(results)} institutions",
                )
                return PullResult(
                    source=self.source_id, series_id=series_id,
                    metadata=meta, observations=observations,
                )
            else:
                return PullResult(
                    source=self.source_id, series_id=series_id,
                    metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                    error=f"Unknown query: '{query_type}'. Use: failures, financials, industry, institution, search",
                )
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _pull_failures(self, series_id, start, end) -> PullResult:
        """Pull historical bank failure data."""
        params = {
            "sort_by": "FAILDATE",
            "sort_order": "ASC",
            "limit": 10000,
            "fields": "CERT,INSTNAME,CITY,STATE,FAILDATE,COST,RESTYPE,PSTALP",
        }

        if start:
            params["filters"] = f"FAILDATE:['{start}' TO *]"
        if end:
            existing = params.get("filters", "")
            if existing:
                params["filters"] = f"{existing} AND FAILDATE:[* TO '{end}']"
            else:
                params["filters"] = f"FAILDATE:[* TO '{end}']"

        data, raw = self._get("failures", **params)

        observations = []
        for item in data.get("data", []):
            d = item.get("data", {})
            fail_date = d.get("FAILDATE", "")
            if not fail_date:
                continue
            # FDIC returns dates as "March 10, 2023" or YYYY-MM-DD
            date_str = self._parse_fdic_date(fail_date)
            cost = d.get("COST")
            observations.append({
                "date": date_str,
                "value": float(cost) if cost else 0,
                "institution": d.get("INSTNAME", ""),
                "city": d.get("CITY", ""),
                "state": d.get("PSTALP", "") or d.get("STATE", ""),
                "cert": d.get("CERT", ""),
                "resolution_type": d.get("RESTYPE", ""),
            })

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title="FDIC Bank Failures",
            frequency="Event", units="USD (thousands)",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]
            meta.notes = f"{len(observations)} failures"

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_financials(self, series_id, cert, field, start, end) -> PullResult:
        """Pull Call Report financials for a specific bank."""
        params = {
            "filters": f"CERT:{cert}",
            "sort_by": "REPDTE",
            "sort_order": "ASC",
            "limit": 500,
            "fields": f"CERT,REPDTE,INSTNAME,{field}",
        }

        data, raw = self._get("financials", **params)

        bank_name = ""
        observations = []
        for item in data.get("data", []):
            d = item.get("data", {})
            repdte = d.get("REPDTE", "")
            if not repdte:
                continue
            date_str = self._repdte_to_date(repdte)
            if start and date_str < start:
                continue
            if end and date_str > end:
                continue

            val = d.get(field)
            if val is None:
                continue
            if not bank_name:
                bank_name = d.get("INSTNAME", f"Cert #{cert}")

            observations.append({
                "date": date_str,
                "value": float(val),
            })

        observations.sort(key=lambda x: x["date"])
        field_name = FINANCIALS_FIELDS.get(field, field)

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{bank_name}: {field_name}",
            frequency="Quarterly", units="USD (thousands)",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_industry(self, series_id, field, start, end) -> PullResult:
        """Pull industry-aggregate financials."""
        params = {
            "sort_by": "REPDTE",
            "sort_order": "ASC",
            "limit": 200,
            "fields": f"REPDTE,{field}",
            "agg_by": "REPDTE",
            "agg_term_fields": f"SUM:{field}",
        }

        data, raw = self._get("financials", **params)

        observations = []
        for item in data.get("data", []):
            d = item.get("data", {})
            repdte = d.get("REPDTE", "")
            if not repdte:
                continue
            date_str = self._repdte_to_date(repdte)
            if start and date_str < start:
                continue
            if end and date_str > end:
                continue
            val = d.get(f"SUM_{field}") or d.get(field)
            if val is None:
                continue
            observations.append({"date": date_str, "value": float(val)})

        observations.sort(key=lambda x: x["date"])
        field_name = FINANCIALS_FIELDS.get(field, field)

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"FDIC Industry Aggregate: {field_name}",
            frequency="Quarterly", units="USD (thousands)",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_institution(self, series_id, cert) -> PullResult:
        """Pull institution details."""
        data, raw = self._get("institutions", filters=f"CERT:{cert}", limit="1")

        items = data.get("data", [])
        if not items:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=f"No institution found with cert #{cert}",
            )

        d = items[0].get("data", {})
        observations = [
            {"date": k, "value": 0, "property": k, "property_value": str(v)}
            for k, v in d.items() if v is not None
        ]

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=d.get("INSTNAME", f"Cert #{cert}"),
            notes=f"City: {d.get('CITY', '')}, State: {d.get('STALP', '')}",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    @staticmethod
    def _parse_fdic_date(date_str: str) -> str:
        """Parse FDIC date formats into YYYY-MM-DD."""
        if not date_str:
            return ""
        # Already ISO format
        if len(date_str) == 10 and date_str[4] == "-":
            return date_str
        # "March 10, 2023" format
        from datetime import datetime
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str

    @staticmethod
    def _repdte_to_date(repdte: str) -> str:
        """Convert FDIC REPDTE (YYYYMMDD) to YYYY-MM-DD."""
        if len(repdte) == 8:
            return f"{repdte[:4]}-{repdte[4:6]}-{repdte[6:8]}"
        return repdte

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for banks by name."""
        results = []

        # Always offer failures and industry
        if any(w in query.lower() for w in ("fail", "close", "collapse", "crisis")):
            results.append(SeriesMetadata(
                source=self.source_id, series_id="failures",
                title="FDIC Bank Failures", frequency="Event",
            ))

        # Search institutions by name
        try:
            data, _ = self._get(
                "institutions",
                search=query,
                fields="CERT,INSTNAME,CITY,STALP,ASSET,ACTIVE",
                sort_by="ASSET",
                sort_order="DESC",
                limit=str(limit),
            )
            for item in data.get("data", []):
                d = item.get("data", {})
                cert = d.get("CERT", "")
                name = d.get("INSTNAME", "")
                city = d.get("CITY", "")
                state = d.get("STALP", "")
                assets = d.get("ASSET")
                asset_str = f" (${assets/1e6:.1f}B)" if assets and assets > 0 else ""
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"financials:{cert}",
                    title=f"{name}{asset_str}",
                    notes=f"Cert #{cert}, {city}, {state}",
                ))
        except Exception:
            pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        parts = series_id.split(":")
        if parts[0] == "failures":
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title="FDIC Bank Failures", frequency="Event",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                "institutions",
                filters="ACTIVE:1",
                fields="CERT,INSTNAME,ASSET",
                sort_by="ASSET",
                sort_order="DESC",
                limit="1",
            )
            items = data.get("data", [])
            if items:
                d = items[0].get("data", {})
                name = d.get("INSTNAME", "?")
                assets = d.get("ASSET", 0)
                return True, f"FDIC: API accessible (largest bank: {name}, ${assets/1e6:.1f}B assets)"
            return False, "FDIC: no data returned"
        except Exception as e:
            return False, f"FDIC: {e}"
