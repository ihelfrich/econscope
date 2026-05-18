"""Shared test fixtures for ECONSCOPE."""

from __future__ import annotations

import os
import pytest
import duckdb
from pathlib import Path


@pytest.fixture
def tmp_warehouse(tmp_path):
    """Create a temporary DuckDB warehouse for testing."""
    db_path = tmp_path / "test_warehouse.duckdb"
    conn = duckdb.connect(str(db_path))

    # Mirror the production schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS time_series (
            source      VARCHAR NOT NULL,
            series_id   VARCHAR NOT NULL,
            date        DATE NOT NULL,
            value       DOUBLE,
            unit        VARCHAR,
            pull_id     VARCHAR NOT NULL,
            PRIMARY KEY (source, series_id, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS series_metadata (
            source          VARCHAR NOT NULL,
            series_id       VARCHAR NOT NULL,
            title           VARCHAR,
            frequency       VARCHAR,
            units           VARCHAR,
            seasonal_adj    VARCHAR,
            last_updated    TIMESTAMP,
            observation_start DATE,
            observation_end   DATE,
            notes           VARCHAR,
            PRIMARY KEY (source, series_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id        VARCHAR PRIMARY KEY,
            level           VARCHAR NOT NULL DEFAULT 'local',
            operation       VARCHAR NOT NULL,
            source          VARCHAR NOT NULL,
            series_id       VARCHAR,
            params          JSON,
            timestamp       TIMESTAMP NOT NULL,
            records_returned INTEGER,
            response_hash   VARCHAR,
            cached          BOOLEAN DEFAULT FALSE,
            assertions      JSON,
            error           VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_manifests (
            job_id          VARCHAR PRIMARY KEY,
            target_name     VARCHAR NOT NULL,
            source          VARCHAR NOT NULL,
            status          VARCHAR NOT NULL DEFAULT 'pending',
            created         TIMESTAMP NOT NULL,
            completed       TIMESTAMP,
            series_requested INTEGER,
            requests_made   INTEGER DEFAULT 0,
            records_pulled  INTEGER DEFAULT 0,
            errors          INTEGER DEFAULT 0,
            retries         INTEGER DEFAULT 0,
            manifest        JSON
        )
    """)

    yield conn
    conn.close()


@pytest.fixture
def has_fred_key():
    """Skip test if FRED API key is not available."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        pytest.skip("FRED_API_KEY not set")
    return key


@pytest.fixture
def has_bls_key():
    """Skip test if BLS API key is not available."""
    key = os.environ.get("BLS_API_KEY")
    if not key:
        pytest.skip("BLS_API_KEY not set")
    return key


@pytest.fixture
def has_eia_key():
    """Skip test if EIA API key is not available."""
    key = os.environ.get("EIA_API_KEY")
    if not key:
        pytest.skip("EIA_API_KEY not set")
    return key


@pytest.fixture
def has_census_key():
    """Skip test if Census API key is not available."""
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        pytest.skip("CENSUS_API_KEY not set")
    return key


@pytest.fixture
def has_finnhub_key():
    """Skip test if Finnhub API key is not available."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        pytest.skip("FINNHUB_API_KEY not set")
    return key


@pytest.fixture
def has_fmp_key():
    """Skip test if FMP API key is not available."""
    key = os.environ.get("FMP_API_KEY")
    if not key:
        pytest.skip("FMP_API_KEY not set")
    return key


@pytest.fixture
def has_comtrade_key():
    """Skip test if Comtrade API key is not available."""
    key = os.environ.get("COMTRADE_API_KEY")
    if not key:
        pytest.skip("COMTRADE_API_KEY not set")
    return key
