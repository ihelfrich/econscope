"""ECONSCOPE CLI — primary interface."""

from __future__ import annotations

import json
import typer
from typing import Optional

app = typer.Typer(
    name="econscope",
    help="Unified economic intelligence platform.",
    no_args_is_help=True,
)

# ── Adapter registry ──────────────────────────────────────────────────────────
# Add new adapters here. Format: source_id → (module_path, class_name)
ADAPTERS = {
    "fred": ("econscope.adapters.fred", "FREDAdapter"),
    "bls": ("econscope.adapters.bls", "BLSAdapter"),
    "bea": ("econscope.adapters.bea", "BEAAdapter"),
    "treasury": ("econscope.adapters.treasury", "TreasuryAdapter"),
    "eia": ("econscope.adapters.eia", "EIAAdapter"),
    "census": ("econscope.adapters.census", "CensusAdapter"),
    "worldbank": ("econscope.adapters.worldbank", "WorldBankAdapter"),
    "dbnomics": ("econscope.adapters.dbnomics", "DBnomicsAdapter"),
    "finnhub": ("econscope.adapters.finnhub", "FinnhubAdapter"),
    "fmp": ("econscope.adapters.fmp", "FMPAdapter"),
    "comtrade": ("econscope.adapters.comtrade", "ComtradeAdapter"),
    "bis": ("econscope.adapters.bis", "BISAdapter"),
    "usda": ("econscope.adapters.usda", "USDAAdapter"),
    "imf": ("econscope.adapters.imf", "IMFAdapter"),
    "noaa": ("econscope.adapters.noaa", "NOAAAdapter"),
    "epa": ("econscope.adapters.epa", "EPAAdapter"),
    "coingecko": ("econscope.adapters.coingecko", "CoinGeckoAdapter"),
    "fao": ("econscope.adapters.faostat", "FAOAdapter"),
    "redfin": ("econscope.adapters.redfin", "RedfinAdapter"),
    "opensanctions": ("econscope.adapters.opensanctions", "OpenSanctionsAdapter"),
    "usaspending": ("econscope.adapters.usaspending", "USASpendingAdapter"),
    "fdic": ("econscope.adapters.fdic", "FDICAdapter"),
    "sec": ("econscope.adapters.sec_edgar", "SECEdgarAdapter"),
    "eurostat": ("econscope.adapters.eurostat", "EurostatAdapter"),
    "oecd": ("econscope.adapters.oecd", "OECDAdapter"),
    "usgs": ("econscope.adapters.usgs", "USGSAdapter"),
    "patents": ("econscope.adapters.patents", "PatentsViewAdapter"),
    "courtlistener": ("econscope.adapters.courtlistener", "CourtListenerAdapter"),
    "gdelt": ("econscope.adapters.gdelt", "GDELTAdapter"),
}


def _get_adapter(source: str):
    if source not in ADAPTERS:
        typer.echo(f"Unknown source: {source}. Available: {', '.join(sorted(ADAPTERS))}")
        raise typer.Exit(1)

    module_path, class_name = ADAPTERS[source]
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


@app.command()
def pull(
    source: str = typer.Argument(..., help="Data source (e.g., fred, bls, bea)"),
    series: str = typer.Argument(..., help="Series ID (e.g., PSAVERT, FEDFUNDS)"),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON instead of storing"),
):
    """Pull a time series from a data source and store it in the warehouse."""
    from econscope.store.warehouse import (
        connect, log_audit, insert_time_series, insert_series_metadata
    )

    adapter = _get_adapter(source)
    typer.echo(f"Pulling {source}:{series}...", err=True)

    result = adapter.pull_series(series, start=start, end=end)

    if not result.ok:
        typer.echo(f"Error: {result.error}", err=True)
        raise typer.Exit(1)

    if raw:
        for obs in result.observations:
            typer.echo(f"{obs['date']}\t{obs['value']}")
        return

    conn = connect()

    audit_id = log_audit(
        conn,
        operation="pull",
        source=source,
        series_id=series,
        params={"start": start, "end": end},
        records_returned=result.count,
        response_data=result.raw_bytes,
        assertions=[
            f"records_returned={result.count}",
            f"series_id_match={result.series_id == series}",
        ],
    )

    insert_series_metadata(conn, source, series, result.metadata.__dict__)
    n = insert_time_series(
        conn, source, series, result.observations, pull_id=audit_id, unit=result.metadata.units
    )
    conn.close()

    typer.echo(
        f"Stored {n} observations for {source}:{series} "
        f"({result.metadata.observation_start} to {result.metadata.observation_end}). "
        f"Audit: {audit_id}",
        err=True,
    )


@app.command()
def search(
    source: str = typer.Argument(..., help="Data source to search"),
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
):
    """Search for series in a data source."""
    adapter = _get_adapter(source)
    results = adapter.search(query, limit=limit)

    if not results:
        typer.echo("No results found.")
        raise typer.Exit(0)

    for r in results:
        freq = f" [{r.frequency}]" if r.frequency else ""
        typer.echo(f"  {r.series_id:20s} {r.title[:60]}{freq}")


@app.command()
def info(
    source: str = typer.Argument(..., help="Data source"),
    series: str = typer.Argument(..., help="Series ID"),
):
    """Show metadata for a series."""
    adapter = _get_adapter(source)
    meta = adapter.get_metadata(series)

    typer.echo(f"Source:     {meta.source}")
    typer.echo(f"Series:     {meta.series_id}")
    typer.echo(f"Title:      {meta.title}")
    typer.echo(f"Frequency:  {meta.frequency}")
    typer.echo(f"Units:      {meta.units}")
    typer.echo(f"Seasonal:   {meta.seasonal_adjustment}")
    typer.echo(f"Range:      {meta.observation_start} to {meta.observation_end}")
    typer.echo(f"Updated:    {meta.last_updated}")
    if meta.notes:
        typer.echo(f"Notes:      {meta.notes[:200]}")


@app.command()
def query(
    source: str = typer.Argument(..., help="Data source"),
    series: str = typer.Argument(..., help="Series ID"),
    start: Optional[str] = typer.Option(None, "--start", "-s"),
    end: Optional[str] = typer.Option(None, "--end", "-e"),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table, csv, json"),
):
    """Query stored data from the warehouse."""
    from econscope.store.warehouse import connect, query_series

    conn = connect()
    rows = query_series(conn, source, series, start=start, end=end)
    conn.close()

    if not rows:
        typer.echo(f"No data for {source}:{series}. Run 'econscope pull {source} {series}' first.")
        raise typer.Exit(0)

    if fmt == "json":
        typer.echo(json.dumps(rows, indent=2))
    elif fmt == "csv":
        typer.echo("date,value")
        for r in rows:
            typer.echo(f"{r['date']},{r['value']}")
    else:
        for r in rows:
            typer.echo(f"  {r['date']}  {r['value']:>12.4f}")


@app.command()
def audit(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of recent audit entries"),
):
    """Show recent audit log entries."""
    from econscope.store.warehouse import connect

    conn = connect()
    rows = conn.execute(
        "SELECT audit_id, operation, source, series_id, timestamp, records_returned, error "
        "FROM audit_log ORDER BY timestamp DESC LIMIT ?",
        [limit],
    ).fetchall()
    conn.close()

    if not rows:
        typer.echo("No audit entries yet.")
        return

    for row in rows:
        aid, op, src, sid, ts, n, err = row
        status = f"{n} records" if not err else f"ERROR: {err}"
        typer.echo(f"  {ts}  {op:6s}  {src}:{sid or ''}  {status}")


@app.command()
def status():
    """Show warehouse contents: series counts, date ranges, storage size."""
    from econscope.store.warehouse import connect
    from econscope.config import WAREHOUSE_PATH

    if not WAREHOUSE_PATH.exists():
        typer.echo("No warehouse found. Run 'econscope pull' to create one.")
        raise typer.Exit(0)

    size_mb = WAREHOUSE_PATH.stat().st_size / (1024 * 1024)
    typer.echo(f"Warehouse: {WAREHOUSE_PATH} ({size_mb:.1f} MB)\n")

    conn = connect()

    # Series count by source
    rows = conn.execute("""
        SELECT source, COUNT(DISTINCT series_id) as series,
               COUNT(*) as observations,
               MIN(date) as earliest, MAX(date) as latest
        FROM time_series GROUP BY source ORDER BY source
    """).fetchall()

    if not rows:
        typer.echo("No data stored yet.")
        conn.close()
        return

    typer.echo(f"{'Source':<10} {'Series':>8} {'Obs':>10} {'Earliest':>12} {'Latest':>12}")
    typer.echo("-" * 56)
    total_series = 0
    total_obs = 0
    for src, n_series, n_obs, earliest, latest in rows:
        typer.echo(f"{src:<10} {n_series:>8} {n_obs:>10,} {str(earliest):>12} {str(latest):>12}")
        total_series += n_series
        total_obs += n_obs
    typer.echo("-" * 56)
    typer.echo(f"{'TOTAL':<10} {total_series:>8} {total_obs:>10,}")

    # Audit log summary
    audit_count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    typer.echo(f"\nAudit log: {audit_count} entries")

    # List all series
    typer.echo(f"\n{'Source':<8} {'Series ID':<25} {'Title':<45} {'Freq':<10}")
    typer.echo("-" * 90)
    meta_rows = conn.execute("""
        SELECT source, series_id, title, frequency
        FROM series_metadata ORDER BY source, series_id
    """).fetchall()
    for src, sid, title, freq in meta_rows:
        typer.echo(f"{src:<8} {sid:<25} {(title or '')[:44]:<45} {freq or '':<10}")

    conn.close()


@app.command()
def batch(
    source: str = typer.Argument(..., help="Data source"),
    series_ids: str = typer.Argument(..., help="Comma-separated series IDs"),
    start: Optional[str] = typer.Option(None, "--start", "-s"),
    end: Optional[str] = typer.Option(None, "--end", "-e"),
):
    """Pull multiple series from a source in one operation."""
    from econscope.store.warehouse import (
        connect, log_audit, insert_time_series, insert_series_metadata
    )

    ids = [s.strip() for s in series_ids.split(",") if s.strip()]
    if not ids:
        typer.echo("No series IDs provided.")
        raise typer.Exit(1)

    adapter = _get_adapter(source)
    conn = connect()

    success = 0
    failed = 0
    total_obs = 0

    for sid in ids:
        typer.echo(f"  Pulling {source}:{sid}...", err=True)
        result = adapter.pull_series(sid, start=start, end=end)

        if not result.ok:
            typer.echo(f"    ERROR: {result.error}", err=True)
            log_audit(conn, operation="pull", source=source, series_id=sid,
                      params={"start": start, "end": end}, error=result.error)
            failed += 1
            continue

        audit_id = log_audit(
            conn, operation="pull", source=source, series_id=sid,
            params={"start": start, "end": end},
            records_returned=result.count, response_data=result.raw_bytes,
        )
        if result.metadata:
            insert_series_metadata(conn, source, sid, result.metadata.__dict__)
        n = insert_time_series(
            conn, source, sid, result.observations, pull_id=audit_id,
            unit=result.metadata.units if result.metadata else None,
        )
        total_obs += n
        success += 1
        typer.echo(f"    {n} observations stored. Audit: {audit_id}", err=True)

    conn.close()
    typer.echo(
        f"\nBatch complete: {success} succeeded, {failed} failed, {total_obs:,} total observations.",
        err=True,
    )


@app.command()
def sources():
    """List available data sources and their status."""
    from econscope.config import get_key

    source_info = {
        "fred": ("FRED", "FRED_API_KEY", "800K+ macro time series"),
        "bls": ("BLS", "BLS_API_KEY", "CPI, employment, wages, JOLTS"),
        "bea": ("BEA", "BEA_API_KEY", "GDP, PCE, personal income, IO tables"),
        "treasury": ("Treasury", "", "Federal debt, rates, spending (no key)"),
        "eia": ("EIA", "EIA_API_KEY", "Crude oil, natural gas, electricity, coal"),
        "census": ("Census", "CENSUS_API_KEY", "ACS, population, business patterns"),
        "worldbank": ("World Bank", "", "15K+ development indicators (no key)"),
        "dbnomics": ("DBnomics", "", "80+ providers: ECB, Eurostat, IMF, OECD (no key)"),
        "finnhub": ("Finnhub", "FINNHUB_API_KEY", "Real-time stocks, fundamentals"),
        "fmp": ("FMP", "FMP_API_KEY", "Financials, ratios, historical prices"),
        "comtrade": ("Comtrade", "COMTRADE_API_KEY", "International bilateral trade"),
        "bis": ("BIS", "", "Cross-border banking, property prices, credit-to-GDP (no key)"),
        "usda": ("USDA NASS", "USDA_NASS_API_KEY", "Crop production, livestock, ag prices"),
        "imf": ("IMF", "", "IFS, BOP, DOTS, WEO (no key)"),
        "noaa": ("NOAA", "", "Temperature, precipitation, drought, 150yr records (no key)"),
        "epa": ("EPA", "", "Emissions, TRI, air quality, Superfund (no key)"),
        "coingecko": ("CoinGecko", "", "18K+ crypto prices, DeFi, market data (no key)"),
        "fao": ("FAOSTAT", "", "Global crops, trade, land use, 245 countries (no key)"),
        "redfin": ("Redfin", "", "US housing: prices, inventory, DOM by ZIP (no key)"),
        "opensanctions": ("OpenSanctions", "", "4.3M entities: sanctions, PEPs, companies (local)"),
        "usaspending": ("USASpending", "", "Federal spending, contracts, grants, loans (no key)"),
        "fdic": ("FDIC", "", "Bank financials, failures, Call Reports (no key)"),
        "sec": ("SEC EDGAR", "", "XBRL company facts, filings, full-text search (no key)"),
        "eurostat": ("Eurostat", "", "EU GDP, unemployment, HICP, trade, demographics (no key)"),
        "oecd": ("OECD", "", "38 countries: GDP, CPI, unemployment, inequality (no key)"),
        "usgs": ("USGS", "", "Earthquakes worldwide: magnitude, depth, location (no key)"),
        "patents": ("PatentsView", "", "USPTO patents: grants, assignees, CPC classes (no key)"),
        "courtlistener": ("CourtListener", "COURTLISTENER_API_TOKEN", "Federal court opinions, dockets, judges, citations"),
        "gdelt": ("GDELT", "", "Global events, news volume, sentiment, geographic hotspots (no key)"),
    }

    typer.echo(f"{'ID':<10} {'Name':<12} {'Key':>5} {'Coverage'}")
    typer.echo("-" * 70)
    for source_id, (name, key_var, coverage) in source_info.items():
        if not key_var:
            has_key = "n/a"  # No key needed
        else:
            has_key = "yes" if get_key(key_var) else "no"
        typer.echo(f"{source_id:<10} {name:<12} {has_key:>5}  {coverage}")


@app.command(name="verify-keys")
def verify_keys():
    """Test all configured API keys."""
    import subprocess
    import sys
    subprocess.run(
        [sys.executable, str(__import__("pathlib").Path(__file__).parent.parent / "scripts" / "verify_keys.py")],
    )


if __name__ == "__main__":
    app()
