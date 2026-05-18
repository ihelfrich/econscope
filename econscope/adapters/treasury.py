"""Treasury FiscalData adapter — U.S. fiscal data (debt, revenue, spending, rates).

No API key required. Public REST API.
Docs: https://fiscaldata.treasury.gov/api-documentation/

Covers: federal debt, revenue, outlays, interest rates, exchange rates,
Treasury securities, savings bonds, debt to the penny.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Well-known endpoints with human-readable names
COMMON_DATASETS = {
    # Debt
    "debt_to_penny": (
        "v2/accounting/od/debt_to_penny",
        "Federal Debt to the Penny",
        "tot_pub_debt_out_amt",
    ),
    "debt_outstanding": (
        "v1/debt/mspd/mspd_table_1",
        "Monthly Statement of Public Debt",
        "total_mil_amt",
    ),
    # Revenue and spending
    "monthly_treasury_statement": (
        "v1/accounting/mts/mts_table_5",
        "Monthly Treasury Statement (Receipts & Outlays)",
        "current_month_gross_rcpt_amt",
    ),
    "daily_treasury_statement": (
        "v1/accounting/dts/dts_table_1",
        "Daily Treasury Statement",
        "close_today_bal",
    ),
    # Interest rates
    "avg_interest_rates": (
        "v2/accounting/od/avg_interest_rates",
        "Average Interest Rates on Treasury Securities",
        "avg_interest_rate_amt",
    ),
    "treasury_rates": (
        "v2/accounting/od/rates_of_exchange",
        "Treasury Reporting Rates of Exchange",
        "exchange_rate",
    ),
    # Savings bonds
    "savings_bonds": (
        "v2/accounting/od/savings_bonds_report",
        "Savings Bonds Report",
        "securities_outstanding_amt",
    ),
    # Budget
    "top_federal_spending": (
        "v2/spending/top_federal",
        "Top Federal Spending Categories",
        "total_spending",
    ),
}


class TreasuryAdapter(BaseAdapter):
    source_id = "treasury"
    source_name = "Treasury FiscalData"
    key_env_var = ""  # No key needed
    requests_per_minute = 60

    BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

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
        """Pull from Treasury FiscalData.

        series_id can be:
          - A common name: "debt_to_penny", "avg_interest_rates"
          - A raw endpoint: "v2/accounting/od/debt_to_penny"
        """
        # Resolve common names
        if series_id in COMMON_DATASETS:
            endpoint, title, value_field = COMMON_DATASETS[series_id]
        else:
            endpoint = series_id
            title = series_id
            value_field = None

        params = {
            "page[size]": "10000",
            "sort": "-record_date",
        }

        # Date filtering
        filters = []
        if start:
            filters.append(f"record_date:gte:{start}")
        if end:
            filters.append(f"record_date:lte:{end}")
        if filters:
            params["filter"] = ",".join(filters)

        try:
            data, raw = self._get(endpoint, **params)
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

        rows = data.get("data", [])
        meta_info = data.get("meta", {})

        # If no value_field specified, try to find a numeric field
        if not value_field and rows:
            # Pick the first field that looks numeric (not date, not text)
            for key in rows[0]:
                if key == "record_date":
                    continue
                try:
                    float(str(rows[0][key]).replace(",", ""))
                    value_field = key
                    break
                except (ValueError, TypeError):
                    continue

        observations = []
        for row in rows:
            date_str = row.get("record_date", "")
            if not date_str:
                continue

            raw_val = row.get(value_field, "") if value_field else ""
            try:
                value = float(str(raw_val).replace(",", ""))
            except (ValueError, TypeError):
                continue

            observations.append({"date": date_str, "value": value})

        observations.sort(key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=title,
            notes=f"Endpoint: {endpoint}, Field: {value_field}",
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
        query_lower = query.lower()
        results = []
        for ds_id, (endpoint, title, _) in COMMON_DATASETS.items():
            if query_lower in title.lower() or query_lower in ds_id.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=ds_id,
                    title=title,
                    notes=f"Endpoint: {endpoint}",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        if series_id in COMMON_DATASETS:
            endpoint, title, _ = COMMON_DATASETS[series_id]
            return SeriesMetadata(
                source=self.source_id,
                series_id=series_id,
                title=title,
                notes=f"Endpoint: {endpoint}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            data, _ = self._get(
                "v2/accounting/od/debt_to_penny",
                **{"page[size]": "1", "sort": "-record_date"}
            )
            if data.get("data"):
                return True, "Treasury FiscalData: API accessible (no key needed)"
            return False, "Treasury FiscalData: no data returned"
        except Exception as e:
            return False, f"Treasury FiscalData: {e}"
