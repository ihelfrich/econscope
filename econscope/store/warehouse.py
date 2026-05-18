"""DuckDB warehouse with full provenance audit trail."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import duckdb

from econscope.config import WAREHOUSE_PATH, DATA_DIR


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> duckdb.DuckDBPyConnection:
    _ensure_dir()
    conn = duckdb.connect(str(WAREHOUSE_PATH))
    _init_schema(conn)
    return conn


def _init_schema(conn: duckdb.DuckDBPyConnection):
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


def log_audit(
    conn: duckdb.DuckDBPyConnection,
    *,
    operation: str,
    source: str,
    series_id: str = None,
    params: dict = None,
    records_returned: int = 0,
    response_data: bytes = None,
    cached: bool = False,
    assertions: List[str] = None,
    error: str = None,
) -> str:
    now = datetime.now(timezone.utc)
    audit_id = f"a-{now.strftime('%Y%m%d-%H%M%S')}-{source}"
    if series_id:
        audit_id += f"-{series_id}"

    response_hash = None
    if response_data:
        response_hash = f"sha256:{hashlib.sha256(response_data).hexdigest()[:16]}"

    conn.execute(
        """
        INSERT INTO audit_log (audit_id, operation, source, series_id, params,
                               timestamp, records_returned, response_hash,
                               cached, assertions, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            audit_id,
            operation,
            source,
            series_id,
            json.dumps(params) if params else None,
            now,
            records_returned,
            response_hash,
            cached,
            json.dumps(assertions) if assertions else None,
            error,
        ],
    )
    return audit_id


def insert_time_series(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    series_id: str,
    observations: list[dict],
    pull_id: str,
    unit: str = None,
):
    if not observations:
        return 0

    conn.executemany(
        """
        INSERT OR REPLACE INTO time_series (source, series_id, date, value, unit, pull_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (source, series_id, obs["date"], obs["value"], unit, pull_id)
            for obs in observations
        ],
    )
    return len(observations)


def insert_series_metadata(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    series_id: str,
    metadata: dict,
):
    def _or_none(val):
        return val if val else None

    conn.execute(
        """
        INSERT OR REPLACE INTO series_metadata
            (source, series_id, title, frequency, units, seasonal_adj,
             last_updated, observation_start, observation_end, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            source,
            series_id,
            metadata.get("title"),
            metadata.get("frequency"),
            metadata.get("units"),
            metadata.get("seasonal_adjustment"),
            _or_none(metadata.get("last_updated")),
            _or_none(metadata.get("observation_start")),
            _or_none(metadata.get("observation_end")),
            metadata.get("notes"),
        ],
    )


def query_series(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    series_id: str,
    start: str = None,
    end: str = None,
) -> list[dict]:
    sql = "SELECT date, value FROM time_series WHERE source = ? AND series_id = ?"
    params = [source, series_id]

    if start:
        sql += " AND date >= ?"
        params.append(start)
    if end:
        sql += " AND date <= ?"
        params.append(end)

    sql += " ORDER BY date"
    result = conn.execute(sql, params).fetchall()
    return [{"date": str(row[0]), "value": row[1]} for row in result]
