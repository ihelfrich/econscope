-- loader.sql — loads Parquet staging files into the DuckDB warehouse.
-- Run after go-ingest pulls data:
--   duckdb data/warehouse.duckdb < go-ingest/loader.sql
--
-- Or from Python:
--   conn.execute(open("go-ingest/loader.sql").read())

-- Upsert staged observations into the main time_series table.
-- Parquet schema: source, series_id, date, value, unit, geo_name, geo_code, extra
INSERT OR REPLACE INTO time_series (source, series_id, date, value, unit, pull_id)
SELECT
    source,
    series_id,
    date,
    value,
    unit,
    'go-ingest-' || current_timestamp::VARCHAR AS pull_id
FROM read_parquet('data/staging/**/*.parquet')
WHERE value IS NOT NULL;
