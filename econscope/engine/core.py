"""ECONSCOPE cross-source query engine.

The layer that makes 29 data sources interoperate. Handles:
- Multi-source pulls: fetch and align multiple series in one call
- Temporal joins: merge series on date with configurable alignment
- Correlation analysis: cross-source correlation matrix
- Entity search: find an entity across all sources simultaneously
- Composite indicators: weighted combinations of series
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from econscope.store.warehouse import connect, insert_time_series, insert_series_metadata, log_audit


# ── Adapter registry (mirrors cli.py but accessible programmatically) ────────

ADAPTER_REGISTRY = {
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

_adapter_cache = {}


def get_adapter(source_id: str):
    """Lazy-load and cache an adapter instance."""
    if source_id not in _adapter_cache:
        if source_id not in ADAPTER_REGISTRY:
            raise ValueError(f"Unknown source: '{source_id}'. Available: {', '.join(sorted(ADAPTER_REGISTRY))}")
        mod_path, cls_name = ADAPTER_REGISTRY[source_id]
        mod = importlib.import_module(mod_path)
        _adapter_cache[source_id] = getattr(mod, cls_name)()
    return _adapter_cache[source_id]


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class SeriesSpec:
    """Specification for a series to pull."""
    source: str
    series_id: str
    label: str = ""  # Human-readable column name for joins
    start: str = None
    end: str = None

    @classmethod
    def parse(cls, spec_str: str) -> "SeriesSpec":
        """Parse 'source:series_id' or 'source:series_id@label' format."""
        label = ""
        if "@" in spec_str:
            spec_str, label = spec_str.rsplit("@", 1)
        parts = spec_str.split(":", 1)
        if len(parts) < 2:
            raise ValueError(f"Series spec must be 'source:series_id', got: '{spec_str}'")
        return cls(source=parts[0], series_id=parts[1], label=label)


@dataclass
class PanelResult:
    """Result of a multi-source pull: aligned date-indexed panel."""
    columns: list[str]  # Column labels
    dates: list[str]  # Sorted date strings
    data: dict[str, dict[str, float]]  # {date: {label: value}}
    metadata: dict[str, dict] = field(default_factory=dict)  # {label: metadata_dict}
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.dates)

    def to_records(self) -> list[dict]:
        """Return as list of flat dicts for easy iteration."""
        records = []
        for date in self.dates:
            row = {"date": date}
            row.update(self.data.get(date, {}))
            records.append(row)
        return records

    def to_csv(self) -> str:
        """Render as CSV string."""
        header = "date," + ",".join(self.columns)
        lines = [header]
        for date in self.dates:
            vals = self.data.get(date, {})
            row = [date] + [str(vals.get(c, "")) for c in self.columns]
            lines.append(",".join(row))
        return "\n".join(lines)

    def to_json(self) -> str:
        """Render as JSON."""
        return json.dumps(self.to_records(), indent=2)


# ── Core engine functions ────────────────────────────────────────────────────

def multi_pull(
    specs: list[SeriesSpec],
    store: bool = True,
) -> PanelResult:
    """Pull multiple series from different sources and align on date.

    Args:
        specs: list of SeriesSpec objects defining what to pull
        store: if True, store results in the warehouse

    Returns:
        PanelResult with aligned data panel
    """
    all_data = {}  # {label: {date: value}}
    metadata = {}
    errors = []
    columns = []

    conn = connect() if store else None

    for spec in specs:
        label = spec.label or f"{spec.source}:{spec.series_id}"
        columns.append(label)

        try:
            adapter = get_adapter(spec.source)
            result = adapter.pull_series(spec.series_id, start=spec.start, end=spec.end)

            if not result.ok:
                errors.append(f"{label}: {result.error}")
                all_data[label] = {}
                continue

            series_data = {}
            for obs in result.observations:
                date = obs.get("date", "")
                value = obs.get("value")
                if date and value is not None:
                    series_data[date] = float(value)

            all_data[label] = series_data

            if result.metadata:
                metadata[label] = {
                    "source": spec.source,
                    "series_id": spec.series_id,
                    "title": result.metadata.title,
                    "units": result.metadata.units,
                    "frequency": result.metadata.frequency,
                    "count": result.count,
                }

            # Store in warehouse
            if store and conn and result.ok:
                audit_id = log_audit(
                    conn, operation="multi_pull", source=spec.source,
                    series_id=spec.series_id,
                    params={"start": spec.start, "end": spec.end, "label": label},
                    records_returned=result.count,
                    response_data=result.raw_bytes,
                )
                if result.metadata:
                    insert_series_metadata(conn, spec.source, spec.series_id, result.metadata.__dict__)
                insert_time_series(
                    conn, spec.source, spec.series_id, result.observations,
                    pull_id=audit_id, unit=result.metadata.units if result.metadata else None,
                )
        except Exception as e:
            errors.append(f"{label}: {e}")
            all_data[label] = {}

    if conn:
        conn.close()

    # Build aligned date index (union of all dates)
    all_dates = set()
    for series_data in all_data.values():
        all_dates.update(series_data.keys())
    sorted_dates = sorted(all_dates)

    # Build date-indexed panel
    panel = {}
    for date in sorted_dates:
        row = {}
        for label in columns:
            val = all_data.get(label, {}).get(date)
            if val is not None:
                row[label] = val
        panel[date] = row

    return PanelResult(
        columns=columns,
        dates=sorted_dates,
        data=panel,
        metadata=metadata,
        errors=errors,
    )


def correlate(
    panel: PanelResult,
    method: str = "pearson",
) -> dict[tuple[str, str], float]:
    """Compute pairwise correlation between all series in a panel.

    Only uses dates where both series have values (inner join).
    Returns dict of {(col_a, col_b): correlation}.
    """
    import math

    results = {}
    cols = panel.columns

    for i, col_a in enumerate(cols):
        for j, col_b in enumerate(cols):
            if j <= i:
                continue

            # Collect paired values
            xs, ys = [], []
            for date in panel.dates:
                row = panel.data.get(date, {})
                if col_a in row and col_b in row:
                    xs.append(row[col_a])
                    ys.append(row[col_b])

            if len(xs) < 3:
                results[(col_a, col_b)] = float("nan")
                continue

            # Pearson correlation
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
            std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs) / n)
            std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)

            if std_x == 0 or std_y == 0:
                results[(col_a, col_b)] = float("nan")
            else:
                results[(col_a, col_b)] = cov / (std_x * std_y)

    return results


def entity_search(
    query: str,
    sources: list[str] = None,
    limit: int = 10,
) -> dict[str, list[dict]]:
    """Search for an entity across multiple sources simultaneously.

    Returns {source_id: [search results]}.
    """
    if sources is None:
        # Default: sources that support meaningful entity search
        sources = [
            "opensanctions", "sec", "fdic", "courtlistener",
            "finnhub", "usaspending",
        ]

    results = {}
    for source_id in sources:
        try:
            adapter = get_adapter(source_id)
            search_results = adapter.search(query, limit=limit)
            results[source_id] = [
                {
                    "series_id": r.series_id,
                    "title": r.title,
                    "frequency": r.frequency,
                    "notes": r.notes,
                }
                for r in search_results
            ]
        except Exception as e:
            results[source_id] = [{"error": str(e)}]

    return results


def warehouse_join(
    series_pairs: list[tuple[str, str]],
    start: str = None,
    end: str = None,
    fill_method: str = "none",
) -> PanelResult:
    """Join multiple series already in the warehouse on date.

    Args:
        series_pairs: list of (source, series_id) tuples
        start: start date filter
        end: end date filter
        fill_method: "none", "forward", "linear" for missing value handling

    Returns:
        PanelResult with joined data
    """
    from econscope.store.warehouse import query_series

    conn = connect()
    all_data = {}
    columns = []
    metadata = {}

    for source, series_id in series_pairs:
        label = f"{source}:{series_id}"
        columns.append(label)

        rows = query_series(conn, source, series_id, start=start, end=end)
        series_data = {row["date"]: row["value"] for row in rows}
        all_data[label] = series_data

        # Get metadata if available
        meta_row = conn.execute(
            "SELECT title, units, frequency FROM series_metadata WHERE source = ? AND series_id = ?",
            [source, series_id],
        ).fetchone()
        if meta_row:
            metadata[label] = {
                "source": source, "series_id": series_id,
                "title": meta_row[0], "units": meta_row[1], "frequency": meta_row[2],
            }

    conn.close()

    # Build date index
    all_dates = set()
    for series_data in all_data.values():
        all_dates.update(series_data.keys())
    sorted_dates = sorted(all_dates)

    # Apply date filter
    if start:
        sorted_dates = [d for d in sorted_dates if d >= start]
    if end:
        sorted_dates = [d for d in sorted_dates if d <= end]

    # Forward fill if requested
    if fill_method == "forward":
        for label in columns:
            last_val = None
            for date in sorted_dates:
                if date in all_data[label]:
                    last_val = all_data[label][date]
                elif last_val is not None:
                    all_data[label][date] = last_val

    # Build panel
    panel = {}
    for date in sorted_dates:
        row = {}
        for label in columns:
            val = all_data.get(label, {}).get(date)
            if val is not None:
                row[label] = val
        panel[date] = row

    return PanelResult(
        columns=columns, dates=sorted_dates,
        data=panel, metadata=metadata,
    )


def summary_stats(panel: PanelResult) -> dict[str, dict[str, float]]:
    """Compute summary statistics for each series in a panel."""
    import math

    stats = {}
    for col in panel.columns:
        values = [
            panel.data[d][col]
            for d in panel.dates
            if col in panel.data.get(d, {})
        ]
        n = len(values)
        if n == 0:
            stats[col] = {"count": 0}
            continue

        mean = sum(values) / n
        sorted_vals = sorted(values)
        median = sorted_vals[n // 2]
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance)

        stats[col] = {
            "count": n,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(std, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "range_start": panel.dates[0] if panel.dates else "",
            "range_end": panel.dates[-1] if panel.dates else "",
        }

        # Add metadata context
        if col in panel.metadata:
            stats[col]["title"] = panel.metadata[col].get("title", "")
            stats[col]["units"] = panel.metadata[col].get("units", "")

    return stats
