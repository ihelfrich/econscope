"""Tests for the BEA adapter (requires BEA_API_KEY)."""

from __future__ import annotations

import os
import pytest
from econscope.adapters.bea import BEAAdapter, COMMON_TABLES


@pytest.fixture
def bea():
    key = os.environ.get("BEA_API_KEY")
    if not key:
        pytest.skip("BEA_API_KEY not set")
    return BEAAdapter()


class TestBEADiscovery:
    def test_get_datasets(self, bea):
        datasets = bea.get_datasets()
        assert len(datasets) >= 10
        names = [d["DatasetName"] for d in datasets]
        assert "NIPA" in names
        assert "Regional" in names

    def test_get_parameters(self, bea):
        params = bea.get_parameters("NIPA")
        assert len(params) > 0
        param_names = [p["ParameterName"] for p in params]
        assert "TableName" in param_names
        assert "Frequency" in param_names

    def test_get_parameter_values(self, bea):
        values = bea.get_parameter_values("NIPA", "TableName")
        assert len(values) > 0


class TestBEASearch:
    def test_search_gdp(self, bea):
        results = bea.search("GDP")
        assert len(results) > 0
        assert all(r.source == "bea" for r in results)

    def test_search_income(self, bea):
        results = bea.search("income")
        assert len(results) > 0

    def test_common_tables_populated(self):
        assert len(COMMON_TABLES) >= 15
        assert "T10101" in COMMON_TABLES
        assert "SAINC1" in COMMON_TABLES


class TestBEAPull:
    def test_pull_nipa_gdp(self, bea):
        result = bea.pull_series("NIPA:T10101:1", start="2023-01-01")
        assert result.ok
        assert result.count > 0
        assert result.metadata.title == "Gross domestic product"
        assert result.metadata.frequency == "Quarterly"

        obs = result.observations[0]
        assert "date" in obs
        assert "value" in obs
        assert isinstance(obs["value"], float)

    def test_pull_nipa_pce(self, bea):
        # Line 2 = Personal consumption expenditures
        result = bea.pull_series("NIPA:T10101:2", start="2024-01-01")
        assert result.ok
        assert result.count >= 1
        assert "consumption" in result.metadata.title.lower()

    def test_pull_regional(self, bea):
        result = bea.pull_series("Regional:SAINC1:3:STATE", start="2022-01-01", end="2022-12-31")
        assert result.ok
        assert result.count >= 50  # at least 50 states
        # Check geo info is included
        assert "geo_name" in result.observations[0]

    def test_pull_bad_format(self, bea):
        result = bea.pull_series("BAD")
        assert not result.ok
        assert "format" in result.error.lower()

    def test_observations_sorted(self, bea):
        result = bea.pull_series("NIPA:T10101:1", start="2020-01-01")
        assert result.ok
        dates = [o["date"] for o in result.observations]
        assert dates == sorted(dates)


class TestBEAHelpers:
    def test_parse_time_period_annual(self):
        assert BEAAdapter._parse_time_period("2024") == "2024-01-01"

    def test_parse_time_period_quarterly(self):
        assert BEAAdapter._parse_time_period("2024Q1") == "2024-01-01"
        assert BEAAdapter._parse_time_period("2024Q2") == "2024-04-01"
        assert BEAAdapter._parse_time_period("2024Q3") == "2024-07-01"
        assert BEAAdapter._parse_time_period("2024Q4") == "2024-10-01"

    def test_parse_time_period_monthly(self):
        assert BEAAdapter._parse_time_period("2024M01") == "2024-01-01"
        assert BEAAdapter._parse_time_period("2024M12") == "2024-12-01"

    def test_parse_time_period_empty(self):
        assert BEAAdapter._parse_time_period("") is None
        assert BEAAdapter._parse_time_period(None) is None

    def test_parse_value_normal(self):
        assert BEAAdapter._parse_value("1234.5") == 1234.5
        assert BEAAdapter._parse_value("1,234,567") == 1234567.0

    def test_parse_value_with_mult(self):
        assert BEAAdapter._parse_value("100", "3") == 100000.0  # 100 * 10^3

    def test_parse_value_na(self):
        assert BEAAdapter._parse_value("(NA)") is None
        assert BEAAdapter._parse_value("(D)") is None
        assert BEAAdapter._parse_value("") is None

    def test_build_year_param(self):
        assert BEAAdapter._build_year_param() == "LAST10"
        assert BEAAdapter._build_year_param("2020-01-01", "2022-12-31") == "2020,2021,2022"
