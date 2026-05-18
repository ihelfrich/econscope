"""Tests for the DuckDB warehouse layer."""

from __future__ import annotations

from econscope.store.warehouse import (
    log_audit, insert_time_series, insert_series_metadata, query_series,
)


def test_insert_and_query(tmp_warehouse):
    conn = tmp_warehouse

    obs = [
        {"date": "2024-01-01", "value": 100.0},
        {"date": "2024-02-01", "value": 101.5},
        {"date": "2024-03-01", "value": 99.8},
    ]

    n = insert_time_series(conn, "test", "TST001", obs, pull_id="test-pull-1")
    assert n == 3

    rows = query_series(conn, "test", "TST001")
    assert len(rows) == 3
    assert rows[0]["date"] == "2024-01-01"
    assert rows[0]["value"] == 100.0
    assert rows[2]["value"] == 99.8


def test_query_with_date_filter(tmp_warehouse):
    conn = tmp_warehouse

    obs = [
        {"date": "2024-01-01", "value": 1.0},
        {"date": "2024-02-01", "value": 2.0},
        {"date": "2024-03-01", "value": 3.0},
        {"date": "2024-04-01", "value": 4.0},
    ]
    insert_time_series(conn, "test", "TST002", obs, pull_id="test-pull-2")

    rows = query_series(conn, "test", "TST002", start="2024-02-01", end="2024-03-01")
    assert len(rows) == 2
    assert rows[0]["value"] == 2.0
    assert rows[1]["value"] == 3.0


def test_upsert_replaces(tmp_warehouse):
    conn = tmp_warehouse

    obs1 = [{"date": "2024-01-01", "value": 100.0}]
    insert_time_series(conn, "test", "TST003", obs1, pull_id="pull-1")

    obs2 = [{"date": "2024-01-01", "value": 105.0}]
    insert_time_series(conn, "test", "TST003", obs2, pull_id="pull-2")

    rows = query_series(conn, "test", "TST003")
    assert len(rows) == 1
    assert rows[0]["value"] == 105.0


def test_empty_insert(tmp_warehouse):
    conn = tmp_warehouse
    n = insert_time_series(conn, "test", "TST004", [], pull_id="pull-empty")
    assert n == 0


def test_audit_log(tmp_warehouse):
    conn = tmp_warehouse

    audit_id = log_audit(
        conn,
        operation="pull",
        source="test",
        series_id="TST005",
        params={"start": "2024-01-01"},
        records_returned=42,
        response_data=b"test response data",
    )

    assert audit_id.startswith("a-")
    assert "test" in audit_id

    rows = conn.execute(
        "SELECT audit_id, operation, source, series_id, records_returned, response_hash "
        "FROM audit_log WHERE audit_id = ?", [audit_id]
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][3] == "TST005"  # series_id
    assert rows[0][4] == 42  # records_returned
    assert rows[0][5].startswith("sha256:")  # response_hash


def test_series_metadata(tmp_warehouse):
    conn = tmp_warehouse

    insert_series_metadata(conn, "test", "TST006", {
        "title": "Test Series",
        "frequency": "Monthly",
        "units": "Percent",
        "seasonal_adjustment": "Seasonally Adjusted",
    })

    rows = conn.execute(
        "SELECT title, frequency, units FROM series_metadata WHERE series_id = 'TST006'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Test Series"
    assert rows[0][1] == "Monthly"
    assert rows[0][2] == "Percent"
