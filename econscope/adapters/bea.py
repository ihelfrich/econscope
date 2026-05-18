"""BEA adapter — Bureau of Economic Analysis (GDP, PCE, personal income, IO tables).

API docs: https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf

Key design notes:
- All requests are GET to https://apps.bea.gov/api/data/
- 13 datasets: NIPA, NIUnderlyingDetail, FixedAssets, ITA, IIP, InputOutput,
  IntlServTrade, IntlServSTA, GDPbyIndustry, UnderlyingGDPbyIndustry,
  Regional, MNE, APIDatasetMetaData
- DataValue is a string; UNIT_MULT is a base-10 exponent
- Rate limit: 100 req/min, 100 MB/min, 30 errors/min
"""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.request import urlopen
from urllib.parse import urlencode

from econscope.config import require_key
from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common NIPA tables for search
COMMON_TABLES = {
    # NIPA
    "T10101": ("NIPA", "Real Gross Domestic Product (chained dollars)"),
    "T10106": ("NIPA", "Real Gross Domestic Product (contributions)"),
    "T10105": ("NIPA", "Gross Domestic Product (price index)"),
    "T10107": ("NIPA", "Gross Domestic Product (percent change)"),
    "T20100": ("NIPA", "Personal Income and Its Disposition"),
    "T20301": ("NIPA", "Personal Consumption Expenditures by Type"),
    "T20305": ("NIPA", "Personal Consumption Expenditures by Function"),
    "T20600": ("NIPA", "Personal Income and Outlays"),
    "T30100": ("NIPA", "Government Current Receipts and Expenditures"),
    "T40100": ("NIPA", "Foreign Transactions"),
    "T50100": ("NIPA", "Saving and Investment"),
    "T50200": ("NIPA", "Saving and Investment by Sector"),
    "T70100": ("NIPA", "GDP by Major Type of Product"),
    # Regional
    "SAINC1": ("Regional", "State Annual Personal Income Summary"),
    "SAINC3": ("Regional", "State Annual Per Capita Personal Income"),
    "SAGDP2N": ("Regional", "State Annual GDP by Industry"),
    "SAGDP9N": ("Regional", "State Annual Real GDP by Industry"),
    "CAINC1": ("Regional", "County Annual Personal Income Summary"),
    "CAINC4": ("Regional", "County Personal Income and Employment"),
    "CAGDP1": ("Regional", "County Annual GDP Summary"),
}


class BEAAdapter(BaseAdapter):
    source_id = "bea"
    source_name = "BEA"
    key_env_var = "BEA_API_KEY"
    requests_per_minute = 100

    BASE = "https://apps.bea.gov/api/data/"

    def __init__(self):
        self.api_key = require_key(self.key_env_var)

    def _get(self, **params) -> tuple[dict, bytes]:
        params["UserID"] = self.api_key
        params["ResultFormat"] = "JSON"
        url = f"{self.BASE}?{urlencode(params)}"
        raw = urlopen(url).read()
        data = json.loads(raw)

        # Check for API errors
        beaapi = data.get("BEAAPI", {})
        results = beaapi.get("Results", {})
        if isinstance(results, dict) and "Error" in results:
            err = results["Error"]
            if isinstance(err, list):
                err = err[0]
            raise RuntimeError(
                f"BEA API error {err.get('APIErrorCode', '?')}: "
                f"{err.get('APIErrorDescription', 'Unknown error')}"
            )

        return data, raw

    # ── Discovery methods ──────────────────────────────────────────────────

    def get_datasets(self) -> list[dict]:
        """List all available BEA datasets."""
        data, _ = self._get(method="GETDATASETLIST")
        return data["BEAAPI"]["Results"]["Dataset"]

    def get_parameters(self, dataset: str) -> list[dict]:
        """List parameters for a dataset (tells you what GETDATA needs)."""
        data, _ = self._get(method="GETPARAMETERLIST", DatasetName=dataset)
        return data["BEAAPI"]["Results"]["Parameter"]

    def get_parameter_values(self, dataset: str, param: str) -> list[dict]:
        """List valid values for a parameter (e.g., TableName options for NIPA)."""
        data, _ = self._get(
            method="GETPARAMETERVALUES",
            DatasetName=dataset,
            ParameterName=param,
        )
        return data["BEAAPI"]["Results"]["ParamValue"]

    def get_parameter_values_filtered(
        self, dataset: str, target_param: str, **filters
    ) -> list[dict]:
        """Get valid values for a parameter filtered by other params.

        Example: get valid LineCodes for a Regional table:
            get_parameter_values_filtered("Regional", "LineCode", TableName="SAINC1")
        """
        data, _ = self._get(
            method="GETPARAMETERVALUESFILTERED",
            DatasetName=dataset,
            TargetParameter=target_param,
            **filters,
        )
        return data["BEAAPI"]["Results"]["ParamValue"]

    # ── Core pull ──────────────────────────────────────────────────────────

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull data from BEA.

        series_id format: DATASET:TABLE:LINECODE[:GEO]
          Examples:
            NIPA:T10101:1           → Real GDP, line 1, quarterly
            Regional:SAINC1:3:STATE → Per capita personal income, all states
            Regional:SAGDP2N:1:STATE → State GDP by industry

        For NIPA/FixedAssets: Frequency is auto-detected (A for annual, Q for quarterly).
        For Regional: GEO defaults to STATE if not specified.
        """
        parts = series_id.split(":")
        if len(parts) < 3:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=(
                    f"Invalid series_id format: '{series_id}'. "
                    "Expected DATASET:TABLE:LINECODE[:GEO]. "
                    "Examples: NIPA:T10101:1, Regional:SAINC1:3:STATE"
                ),
            )

        dataset = parts[0]
        table_name = parts[1]
        line_code = parts[2]
        geo = parts[3] if len(parts) > 3 else None

        # Build year param
        years = self._build_year_param(start, end)

        try:
            if dataset == "Regional":
                return self._pull_regional(
                    series_id, table_name, line_code, geo or "STATE", years
                )
            elif dataset in ("NIPA", "NIUnderlyingDetail"):
                return self._pull_nipa(series_id, dataset, table_name, line_code, years)
            elif dataset == "FixedAssets":
                return self._pull_fixed_assets(series_id, table_name, line_code, years)
            elif dataset == "GDPbyIndustry":
                return self._pull_gdp_by_industry(series_id, table_name, line_code, years)
            else:
                return PullResult(
                    source=self.source_id,
                    series_id=series_id,
                    metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                    error=f"Dataset '{dataset}' not yet supported. "
                          f"Supported: NIPA, Regional, FixedAssets, GDPbyIndustry.",
                )
        except Exception as e:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _pull_nipa(
        self, series_id: str, dataset: str, table_name: str,
        line_code: str, years: str
    ) -> PullResult:
        """Pull from NIPA or NIUnderlyingDetail."""
        # Try quarterly first, fall back to annual
        for freq in ["Q", "A"]:
            try:
                data, raw = self._get(
                    method="GETDATA",
                    DatasetName=dataset,
                    TableName=table_name,
                    Frequency=freq,
                    Year=years,
                )
                break
            except RuntimeError as e:
                if freq == "A":
                    raise
                continue

        return self._parse_data_response(series_id, data, raw, line_code=line_code)

    def _pull_regional(
        self, series_id: str, table_name: str, line_code: str,
        geo: str, years: str
    ) -> PullResult:
        data, raw = self._get(
            method="GETDATA",
            DatasetName="Regional",
            TableName=table_name,
            LineCode=line_code,
            GeoFips=geo,
            Year=years,
        )
        # Regional API filters by LineCode server-side; don't re-filter
        return self._parse_data_response(series_id, data, raw)

    def _pull_fixed_assets(
        self, series_id: str, table_name: str, line_code: str, years: str
    ) -> PullResult:
        data, raw = self._get(
            method="GETDATA",
            DatasetName="FixedAssets",
            TableName=table_name,
            Year=years,
        )
        return self._parse_data_response(series_id, data, raw, line_code=line_code)

    def _pull_gdp_by_industry(
        self, series_id: str, table_id: str, industry: str, years: str
    ) -> PullResult:
        data, raw = self._get(
            method="GETDATA",
            DatasetName="GDPbyIndustry",
            TableID=table_id,
            Frequency="Q",
            Industry=industry,
            Year=years,
        )
        return self._parse_data_response(series_id, data, raw)

    def _parse_data_response(
        self, series_id: str, data: dict, raw: bytes,
        line_code: str = None,
    ) -> PullResult:
        """Parse BEAAPI response into observations."""
        results = data["BEAAPI"]["Results"]

        data_rows = results.get("Data", [])
        if not data_rows:
            return PullResult(
                source=self.source_id,
                series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                observations=[],
                raw_bytes=raw,
                error="No data returned",
            )

        # Filter to requested line code (API often returns all lines)
        if line_code:
            data_rows = [r for r in data_rows if r.get("LineNumber", "") == str(line_code)]

        # Extract metadata from first matching row
        first = data_rows[0] if data_rows else {}
        meta = SeriesMetadata(
            source=self.source_id,
            series_id=series_id,
            title=first.get("LineDescription", results.get("Statistic", "")),
            units=first.get("CL_UNIT", results.get("UnitOfMeasure", "")),
            frequency=self._detect_frequency(data_rows),
            notes=results.get("PublicTable", ""),
        )

        observations = []
        for row in data_rows:
            time_period = row.get("TimePeriod", "")
            data_value = row.get("DataValue", "")

            date_str = self._parse_time_period(time_period)
            if not date_str:
                continue

            value = self._parse_value(data_value, row.get("UNIT_MULT", "0"))
            if value is None:
                continue

            obs = {"date": date_str, "value": value}

            # For Regional data, include geo info
            geo_name = row.get("GeoName", "")
            geo_fips = row.get("GeoFips", "")
            if geo_name:
                obs["geo_name"] = geo_name
                obs["geo_fips"] = geo_fips

            observations.append(obs)

        observations.sort(key=lambda x: x["date"])

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

    @staticmethod
    def _detect_frequency(rows: list[dict]) -> str:
        """Guess frequency from TimePeriod format."""
        for r in rows[:5]:
            tp = r.get("TimePeriod", "")
            if "Q" in tp:
                return "Quarterly"
            if "M" in tp:
                return "Monthly"
        return "Annual"

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search common BEA tables by keyword."""
        query_lower = query.lower()
        results = []
        for table_id, (dataset, title) in COMMON_TABLES.items():
            if query_lower in title.lower() or query_lower in table_id.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"{dataset}:{table_id}",
                    title=title,
                    notes=f"Dataset: {dataset}",
                ))
        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        """Get metadata for a BEA table."""
        parts = series_id.split(":")
        if len(parts) >= 2:
            dataset, table = parts[0], parts[1]
            if table in COMMON_TABLES:
                ds, title = COMMON_TABLES[table]
                return SeriesMetadata(
                    source=self.source_id,
                    series_id=series_id,
                    title=title,
                    notes=f"Dataset: {ds}",
                )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_year_param(start: str = None, end: str = None) -> str:
        """Convert start/end dates to BEA Year param."""
        if not start and not end:
            return "LAST10"

        start_year = int(start[:4]) if start else 2000
        end_year = int(end[:4]) if end else 2026

        if end_year - start_year > 30:
            return "ALL"

        years = list(range(start_year, end_year + 1))
        return ",".join(str(y) for y in years)

    @staticmethod
    def _parse_time_period(tp: str) -> Optional[str]:
        """Convert BEA TimePeriod to YYYY-MM-DD.

        Handles: "2024", "2024Q1", "2024Q2", "2024M01", "2024M12"
        """
        if not tp:
            return None

        tp = tp.strip()

        if len(tp) == 4 and tp.isdigit():
            return f"{tp}-01-01"

        if "Q" in tp:
            parts = tp.split("Q")
            year = parts[0]
            quarter = int(parts[1])
            month = {1: "01", 2: "04", 3: "07", 4: "10"}.get(quarter, "01")
            return f"{year}-{month}-01"

        if "M" in tp:
            parts = tp.split("M")
            year = parts[0]
            month = parts[1].zfill(2)
            return f"{year}-{month}-01"

        return None

    @staticmethod
    def _parse_value(data_value: str, unit_mult: str = "0") -> Optional[float]:
        """Parse BEA DataValue string to float, applying UNIT_MULT."""
        if not data_value or data_value in ("(NA)", "(D)", "(L)", "(NM)", "..."):
            return None

        try:
            cleaned = data_value.replace(",", "").strip()
            value = float(cleaned)
            mult = int(unit_mult) if unit_mult else 0
            if mult != 0:
                value *= 10 ** mult
            return value
        except (ValueError, TypeError):
            return None

    def verify_key(self) -> tuple[bool, str]:
        try:
            datasets = self.get_datasets()
            if datasets:
                return True, f"BEA: key valid ({len(datasets)} datasets available)"
            return False, "BEA: key returned no datasets"
        except Exception as e:
            return False, f"BEA: {e}"
