"""Build facts for a Cueline forensic-economics reference deck.

The live assistant should retrieve concise facts, not infer values from a large
table in the middle of a meeting. This module converts official observations
into small attributed blocks while retaining recent values, the calculation
rule, observation date, retrieval time, and raw-response hash.
"""

from __future__ import annotations

import hashlib
import html as html_module
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class FactSeries:
    source: str
    series_id: str
    title: str
    category: str
    units: str
    seasonal_adjustment: str
    transform: str
    decimals: int
    source_url: str
    tags: tuple[str, ...] = ()


FORENSIC_SERIES = (
    # Inflation and escalation. The SA indexes support clean month-to-month
    # comparisons while the 12-month changes are calculated locally.
    FactSeries("bls", "CUSR0000SA0", "CPI-U, all items", "Inflation and escalation",
               "Index 1982-84=100", "Seasonally adjusted", "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CUSR0000SA0", ("CPI", "inflation", "escalation")),
    FactSeries("bls", "CUSR0000SA0L1E", "CPI-U, all items less food and energy",
               "Inflation and escalation", "Index 1982-84=100", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CUSR0000SA0L1E", ("core CPI", "inflation")),
    FactSeries("bls", "CUSR0000SAH1", "CPI-U, shelter", "Inflation and escalation",
               "Index 1982-84=100", "Seasonally adjusted", "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CUSR0000SAH1", ("shelter", "housing", "CPI")),
    FactSeries("bls", "CUUR0000SAM", "CPI-U, medical care", "Inflation and escalation",
               "Index 1982-84=100", "Not seasonally adjusted", "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CUUR0000SAM", ("medical care", "CPI")),

    # Labor-market levels, earnings, churn, and compensation-cost indexes.
    FactSeries("bls", "LNS14000000", "Unemployment rate", "Labor market and earnings",
               "Percent", "Seasonally adjusted", "latest_and_yoy_points", 1,
               "https://data.bls.gov/timeseries/LNS14000000", ("unemployment", "labor market")),
    FactSeries("bls", "LNS11300000", "Labor-force participation rate", "Labor market and earnings",
               "Percent", "Seasonally adjusted", "latest_and_yoy_points", 1,
               "https://data.bls.gov/timeseries/LNS11300000", ("participation", "labor force")),
    FactSeries("bls", "LNS12300000", "Employment-population ratio", "Labor market and earnings",
               "Percent", "Seasonally adjusted", "latest_and_yoy_points", 1,
               "https://data.bls.gov/timeseries/LNS12300000", ("employment", "population")),
    FactSeries("bls", "CES0000000001", "Total nonfarm payroll employment",
               "Labor market and earnings", "Thousands of jobs", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CES0000000001", ("payroll", "employment", "CES")),
    FactSeries("bls", "CES0500000003", "Average hourly earnings, total private",
               "Labor market and earnings", "Dollars per hour", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CES0500000003", ("earnings", "wages", "hourly")),
    FactSeries("bls", "CES0500000011", "Average weekly earnings, total private",
               "Labor market and earnings", "Dollars per week", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CES0500000011", ("earnings", "weekly", "wages")),
    FactSeries("bls", "CES0500000002", "Average weekly hours, total private",
               "Labor market and earnings", "Hours per week", "Seasonally adjusted", "latest", 1,
               "https://data.bls.gov/timeseries/CES0500000002", ("hours", "workweek")),
    FactSeries("bls", "JTS000000000000000JOL", "Job openings",
               "Labor market and earnings", "Thousands of openings", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/JTS000000000000000JOL", ("JOLTS", "openings")),
    FactSeries("bls", "JTS000000000000000JOR", "Job-openings rate",
               "Labor market and earnings", "Percent", "Seasonally adjusted",
               "latest_and_yoy_points", 1,
               "https://data.bls.gov/timeseries/JTS000000000000000JOR", ("JOLTS", "openings rate")),
    FactSeries("bls", "JTS000000000000000QUL", "Quits",
               "Labor market and earnings", "Thousands of quits", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/JTS000000000000000QUL", ("JOLTS", "quits")),
    FactSeries("bls", "JTS000000000000000QUR", "Quits rate",
               "Labor market and earnings", "Percent", "Seasonally adjusted",
               "latest_and_yoy_points", 1,
               "https://data.bls.gov/timeseries/JTS000000000000000QUR", ("JOLTS", "quits rate")),
    FactSeries("bls", "LEU0252881500", "Median usual weekly earnings, full-time workers",
               "Labor market and earnings", "Dollars per week", "Seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/LEU0252881500", ("median earnings", "full-time")),
    FactSeries("bls", "CIU1010000000000A", "Employment Cost Index, total compensation, civilian workers",
               "Labor market and earnings", "Index 2005=100", "Not seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CIU1010000000000A", ("ECI", "compensation", "benefits")),
    FactSeries("bls", "CIU1020000000000A", "Employment Cost Index, wages and salaries, civilian workers",
               "Labor market and earnings", "Index 2005=100", "Not seasonally adjusted",
               "latest_and_yoy_percent", 1,
               "https://data.bls.gov/timeseries/CIU1020000000000A", ("ECI", "wages")),

    # BEA-origin series distributed through FRED's public graph export.
    FactSeries("fred", "A191RL1Q225SBEA", "Real GDP growth at a seasonally adjusted annual rate",
               "Macroeconomic income and growth", "Percent", "Seasonally adjusted annual rate",
               "latest", 1, "https://fred.stlouisfed.org/series/A191RL1Q225SBEA",
               ("GDP", "growth", "BEA")),
    FactSeries("fred", "PCEPI", "PCE price index", "Inflation and escalation",
               "Index 2017=100", "Seasonally adjusted", "latest_and_yoy_percent", 1,
               "https://fred.stlouisfed.org/series/PCEPI", ("PCE", "inflation", "BEA")),
    FactSeries("fred", "PCEPILFE", "Core PCE price index", "Inflation and escalation",
               "Index 2017=100", "Seasonally adjusted", "latest_and_yoy_percent", 1,
               "https://fred.stlouisfed.org/series/PCEPILFE", ("core PCE", "inflation", "BEA")),
    FactSeries("fred", "DSPIC96", "Real disposable personal income",
               "Macroeconomic income and growth", "Billions of chained 2017 dollars, annual rate",
               "Seasonally adjusted", "latest_and_yoy_percent", 1,
               "https://fred.stlouisfed.org/series/DSPIC96", ("income", "disposable income", "BEA")),
    FactSeries("fred", "PSAVERT", "Personal saving rate",
               "Macroeconomic income and growth", "Percent", "Seasonally adjusted annual rate",
               "latest", 1, "https://fred.stlouisfed.org/series/PSAVERT", ("saving", "income")),
    FactSeries("fred", "FEDFUNDS", "Federal funds effective rate", "Discount and interest rates",
               "Percent", "Monthly average", "latest", 2,
               "https://fred.stlouisfed.org/series/FEDFUNDS", ("interest rate", "discount rate", "Federal Reserve")),
)


@dataclass(frozen=True)
class CalculatedFact:
    text: str
    as_of: str
    value: float
    change: Optional[float] = None


@dataclass(frozen=True)
class CorpusBuildResult:
    root: Path
    snapshot_dir: Path
    deck_path: Path
    markdown_path: Path
    manifest_path: Path
    fact_count: int
    errors: tuple[str, ...]


def _format_number(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}"


def _format_level(spec: FactSeries, value: float) -> str:
    unit = spec.units.lower()
    number = _format_number(value, spec.decimals)
    if unit == "percent":
        return f"{number}%"
    if unit.startswith("dollars per hour"):
        return f"${number} per hour"
    if unit.startswith("dollars per week"):
        return f"${number} per week"
    return f"{number} {spec.units}".strip()


def _year_ago(observations: list[dict], latest_date: str) -> Optional[dict]:
    try:
        target = f"{int(latest_date[:4]) - 1}{latest_date[4:]}"
    except (ValueError, TypeError):
        return None
    exact = next((item for item in observations if item["date"] == target), None)
    if exact:
        return exact
    # Quarterly and irregular series sometimes move the observation day. The
    # nearest observation in the target year/month is still the same period.
    return next((item for item in observations if item["date"][:7] == target[:7]), None)


def calculate_fact(spec: FactSeries, observations: Iterable[dict]) -> CalculatedFact:
    ordered = sorted(
        (item for item in observations if item.get("date") and item.get("value") is not None),
        key=lambda item: item["date"],
    )
    if not ordered:
        raise ValueError(f"{spec.source}:{spec.series_id} has no usable observations")
    latest = ordered[-1]
    level = _format_level(spec, float(latest["value"]))
    prefix = f"As of {latest['date']}, {spec.title} was {level}."

    if spec.transform == "latest":
        return CalculatedFact(prefix, latest["date"], float(latest["value"]))

    previous = _year_ago(ordered, latest["date"])
    if not previous:
        raise ValueError(f"{spec.source}:{spec.series_id} has no year-earlier observation")

    prior = float(previous["value"])
    current = float(latest["value"])
    if spec.transform == "latest_and_yoy_percent":
        if prior == 0:
            raise ValueError(f"{spec.source}:{spec.series_id} cannot calculate growth from zero")
        change = round((current / prior - 1.0) * 100.0, spec.decimals)
        text = (
            f"{prefix} Its 12-month change was {_format_number(change, spec.decimals)}%, "
            f"calculated from the published index levels for {previous['date']} and {latest['date']}."
        )
        return CalculatedFact(text, latest["date"], current, change)

    if spec.transform == "latest_and_yoy_points":
        change = round(current - prior, spec.decimals)
        sign = "+" if change >= 0 else ""
        text = (
            f"{prefix} That was {sign}{_format_number(change, spec.decimals)} percentage points "
            f"from {previous['date']}."
        )
        return CalculatedFact(text, latest["date"], current, change)

    raise ValueError(f"Unknown fact transform: {spec.transform}")


TREASURY_FIELDS = {
    "BC_1MONTH": "1-month",
    "BC_1_5MONTH": "1.5-month",
    "BC_2MONTH": "2-month",
    "BC_3MONTH": "3-month",
    "BC_4MONTH": "4-month",
    "BC_6MONTH": "6-month",
    "BC_1YEAR": "1-year",
    "BC_2YEAR": "2-year",
    "BC_3YEAR": "3-year",
    "BC_5YEAR": "5-year",
    "BC_7YEAR": "7-year",
    "BC_10YEAR": "10-year",
    "BC_20YEAR": "20-year",
    "BC_30YEAR": "30-year",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_treasury_curve(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    rows = []
    for properties in root.iter():
        if _local_name(properties.tag) != "properties":
            continue
        row = {}
        for child in properties:
            name = _local_name(child.tag)
            value = (child.text or "").strip()
            if name == "NEW_DATE" and value:
                row["date"] = value[:10]
            elif name in TREASURY_FIELDS and value:
                try:
                    row[TREASURY_FIELDS[name]] = float(value)
                except ValueError:
                    pass
        if row.get("date") and len(row) > 1:
            rows.append(row)
    if not rows:
        raise ValueError("Treasury feed returned no yield-curve rows")
    return max(rows, key=lambda row: row["date"])


def raw_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _html_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_module.unescape(text)).strip()


def _month_date(month: str, year: str) -> str:
    months = {
        "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4,
        "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8,
        "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
    }
    return f"{int(year):04d}-{months[month.upper()]:02d}-01"


def extract_ecec_facts(raw: bytes, *, retrieved_at: str) -> list[dict]:
    text = _html_text(raw)
    number = r"(\d+(?:\.\d+)?)"
    period = re.search(
        r"EMPLOYER COSTS FOR EMPLOYEE COMPENSATION\s*[-–—]\s*([A-Z]+)\s+(\d{4})",
        text, flags=re.I,
    )
    civilian = re.search(
        rf"civilian workers averaged \${number} per hour worked in\s+[A-Za-z]+\s+\d{{4}}\.\s*"
        rf"Wages and salaries averaged \${number}, while benefit costs averaged \${number}",
        text, flags=re.I,
    )
    private = re.search(
        rf"private industry workers averaged \${number} per hour worked\.\s*"
        rf"Wages and salaries averaged \${number} per hour worked and accounted for {number} percent"
        rf".*?benefit costs averaged \${number} per hour worked and accounted for (?:the remaining )?{number} percent",
        text, flags=re.I,
    )
    if not (period and civilian and private):
        raise ValueError("Current ECEC release did not match its published summary structure")
    as_of = _month_date(period.group(1), period.group(2))
    digest = raw_hash(raw)
    source_url = "https://www.bls.gov/news.release/ecec.htm"
    civilian_values = [float(value) for value in civilian.groups()]
    private_values = [float(value) for value in private.groups()]
    entries = [
        (
            FactSeries("bls", "ECEC-current-civilian", "Employer compensation cost, civilian workers",
                       "Fringe benefits and compensation", "Dollars per hour", "Point-in-time estimate",
                       "latest", 2, source_url, ("ECEC", "benefits", "compensation")),
            f"In {period.group(1).title()} {period.group(2)}, employer compensation costs for civilian "
            f"workers averaged ${civilian_values[0]:.2f} per hour: ${civilian_values[1]:.2f} in wages "
            f"and salaries and ${civilian_values[2]:.2f} in benefit costs.",
            civilian_values[0],
        ),
        (
            FactSeries("bls", "ECEC-current-private", "Employer compensation cost, private industry",
                       "Fringe benefits and compensation", "Dollars per hour", "Point-in-time estimate",
                       "latest", 2, source_url, ("ECEC", "benefits", "private industry")),
            f"In {period.group(1).title()} {period.group(2)}, private-industry employer compensation "
            f"costs averaged ${private_values[0]:.2f} per hour. Wages and salaries were "
            f"${private_values[1]:.2f} ({private_values[2]:.1f}%); benefits were "
            f"${private_values[3]:.2f} ({private_values[4]:.1f}%).",
            private_values[0],
        ),
    ]
    return [{
        "spec": spec,
        "text": fact_text,
        "as_of": as_of,
        "observations": [{"date": as_of, "value": value}],
        "raw_hash": digest,
    } for spec, fact_text, value in entries]


def extract_atus_facts(raw: bytes, *, retrieved_at: str) -> list[dict]:
    text = _html_text(raw)
    period = re.search(r"AMERICAN TIME USE SURVEY\s*[-–—]\s*(\d{4}) RESULTS", text, flags=re.I)
    household = re.search(
        r"Household activities\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)", text, flags=re.I,
    )
    under_six = re.search(
        r"Child under age 6\s+Caring for household children as a primary activity\s+"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)", text, flags=re.I,
    )
    if not (period and household and under_six):
        raise ValueError("Current ATUS release did not match its published tables")
    year = period.group(1)
    as_of = f"{year}-01-01"
    digest = raw_hash(raw)
    source_url = "https://www.bls.gov/news.release/atus.htm"
    h = [float(value) for value in household.groups()]
    c = [float(value) for value in under_six.groups()]
    entries = [
        (
            FactSeries("bls", "ATUS-household-activities", "Time spent on household activities",
                       "Household services and time use", "Hours per day", "Annual average",
                       "latest", 2, source_url, ("ATUS", "household services", "time use")),
            f"In {year}, people age 15 and over averaged {h[0]:.2f} hours per day in household "
            f"activities (men {h[1]:.2f}; women {h[2]:.2f}). {h[3]:.1f}% engaged on an average "
            f"day (men {h[4]:.1f}%; women {h[5]:.1f}%). A primary activity excludes simultaneous activities.",
            h[0],
        ),
        (
            FactSeries("bls", "ATUS-primary-childcare-under-6",
                       "Primary childcare time for adults with a child under age 6",
                       "Household services and time use", "Hours per day", "Annual average",
                       "latest", 2, source_url, ("ATUS", "childcare", "household services")),
            f"In {year}, adults in households with a child under age 6 averaged {c[0]:.2f} hours per "
            f"day caring for household children as a primary activity (men {c[1]:.2f}; women {c[2]:.2f}).",
            c[0],
        ),
    ]
    return [{
        "spec": spec,
        "text": fact_text,
        "as_of": as_of,
        "observations": [{"date": as_of, "value": value}],
        "raw_hash": digest,
    } for spec, fact_text, value in entries]


def extract_cdc_life_expectancy_fact(raw: bytes, *, retrieved_at: str) -> dict:
    text = _html_text(raw)
    match = re.search(r"Life expectancy:\s*([\d.]+) years", text, flags=re.I)
    year = re.search(r"Mortality Data \((\d{4})\)|Mortality in the United States,?\s*(\d{4})", text, flags=re.I)
    if not (match and year):
        raise ValueError("CDC mortality page did not expose a dated life-expectancy value")
    data_year = next(group for group in year.groups() if group)
    value = float(match.group(1))
    as_of = f"{data_year}-01-01"
    spec = FactSeries(
        "cdc", "life-expectancy-at-birth-current", "U.S. life expectancy at birth",
        "Life expectancy and demography", "Years", "Final mortality data",
        "latest", 1, "https://www.cdc.gov/nchs/fastats/deaths.htm",
        ("life expectancy", "mortality", "NVSS"),
    )
    return {
        "spec": spec,
        "text": (
            f"Final {data_year} mortality data put U.S. life expectancy at birth at {value:.1f} years. "
            "This headline value is not a substitute for age- and sex-specific remaining-life "
            "expectancy from a complete life table."
        ),
        "as_of": as_of,
        "observations": [{"date": as_of, "value": value}],
        "raw_hash": raw_hash(raw),
    }


def extract_oews_summary_fact(raw: bytes, *, retrieved_at: str) -> dict:
    text = _html_text(raw)
    period = re.search(r"OCCUPATIONAL EMPLOYMENT AND WAGES\s*[-–—]+\s*([A-Z]+)\s+(\d{4})", text, flags=re.I)
    wage = re.search(r"U\.S\. average wage of \$([\d,]+)", text, flags=re.I)
    occupations = re.search(r"estimates for about ([\d,]+) occupations", text, flags=re.I)
    if not (period and wage and occupations):
        raise ValueError("Current OEWS release did not expose its coverage and national mean wage")
    as_of = _month_date(period.group(1), period.group(2))
    value = float(wage.group(1).replace(",", ""))
    count = int(occupations.group(1).replace(",", ""))
    spec = FactSeries(
        "bls", "OEWS-current-national", "OEWS national occupational wage benchmark",
        "Replacement wages and occupational earnings", "Dollars per year", "Annual estimate",
        "latest", 0, "https://www.bls.gov/news.release/ocwage.nr0.htm",
        ("OEWS", "replacement cost", "occupational wages"),
    )
    return {
        "spec": spec,
        "text": (
            f"The {period.group(1).title()} {period.group(2)} OEWS release covers about {count:,} "
            f"occupations and reports a U.S. all-occupations annual mean wage of ${value:,.0f}. "
            "Occupation-specific replacement wages should come from the downloaded OEWS tables, "
            "with the geography and wage statistic stated explicitly."
        ),
        "as_of": as_of,
        "observations": [{"date": as_of, "value": value}],
        "raw_hash": raw_hash(raw),
    }


def _download_record(name: str, url: str, raw: bytes) -> dict:
    return {"file": name, "url": url, "bytes": len(raw), "sha256": raw_hash(raw)}


def _freshness_limit_days(spec: FactSeries) -> int:
    if spec.series_id in {"A191RL1Q225SBEA", "LEU0252881500"} or spec.series_id.startswith("CIU"):
        return 220
    if spec.series_id.startswith("JTS"):
        return 130
    if spec.source == "fred":
        return 100
    return 90


def _fresh_enough(spec: FactSeries, as_of: str, today: Date) -> tuple[bool, str]:
    try:
        observation_date = Date.fromisoformat(as_of)
    except ValueError:
        return False, f"{spec.source}:{spec.series_id} returned an invalid date: {as_of}"
    age = (today - observation_date).days
    if age < -3:
        return False, f"{spec.source}:{spec.series_id} returned a future observation: {as_of}"
    limit = _freshness_limit_days(spec)
    if age > limit:
        return False, (
            f"{spec.source}:{spec.series_id} latest observation {as_of} is {age} days old "
            f"(freshness limit {limit})"
        )
    return True, ""


def _store_pull(result, spec: FactSeries, *, start: str, end: str, errors: list[str]) -> None:
    try:
        from econscope.store.warehouse import (
            connect, insert_series_metadata, insert_time_series, log_audit,
        )
        conn = connect()
        audit_id = log_audit(
            conn, operation="forensic-corpus", source=spec.source,
            series_id=spec.series_id, params={"start": start, "end": end},
            records_returned=result.count, response_data=result.raw_bytes,
            assertions=["source_downloaded", "fact_transform_explicit"],
        )
        insert_series_metadata(conn, spec.source, spec.series_id, {
            **result.metadata.__dict__,
            "title": spec.title,
            "units": spec.units,
            "seasonal_adjustment": spec.seasonal_adjustment,
        })
        insert_time_series(
            conn, spec.source, spec.series_id, result.observations,
            pull_id=audit_id, unit=spec.units,
        )
        conn.close()
    except Exception as error:
        errors.append(f"Warehouse store failed for {spec.source}:{spec.series_id}: {error}")


def build_current_corpus(*, root: Optional[Path] = None, now: Optional[datetime] = None) -> CorpusBuildResult:
    """Download current forensic-economics inputs and emit a Cueline deck."""
    from econscope.adapters.bls import BLSAdapter
    from econscope.adapters.fred import FREDAdapter
    from econscope.config import DATA_DIR
    from econscope.intel.http import fetch

    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    retrieved_at = instant.isoformat().replace("+00:00", "Z")
    today = instant.date()
    start = f"{today.year - 2}-01-01"
    end = today.isoformat()
    root = Path(root) if root else DATA_DIR / "corpora" / "forensic-economics"

    facts: list[dict] = []
    raw_downloads: dict[str, bytes] = {}
    downloads: list[dict] = []
    errors: list[str] = []

    bls_specs = [spec for spec in FORENSIC_SERIES if spec.source == "bls"]
    bls_results = BLSAdapter().pull_batch(
        [spec.series_id for spec in bls_specs], start=start, end=end
    )
    result_by_id = {result.series_id: result for result in bls_results}
    bls_raw = next((result.raw_bytes for result in bls_results if result.raw_bytes), b"")
    if bls_raw:
        name = "bls-public-timeseries.json"
        raw_downloads[name] = bls_raw
        downloads.append(_download_record(
            name, "https://api.bls.gov/publicAPI/v2/timeseries/data/", bls_raw
        ))
    for spec in bls_specs:
        result = result_by_id.get(spec.series_id)
        if not result or not result.ok:
            errors.append(f"BLS {spec.series_id}: {getattr(result, 'error', 'missing result')}")
            continue
        try:
            calculated = calculate_fact(spec, result.observations)
            fresh, warning = _fresh_enough(spec, calculated.as_of, today)
            if not fresh:
                errors.append(warning)
                continue
            facts.append({
                "spec": spec, "text": calculated.text, "as_of": calculated.as_of,
                "observations": result.observations, "raw_hash": raw_hash(result.raw_bytes),
            })
            _store_pull(result, spec, start=start, end=end, errors=errors)
        except Exception as error:
            errors.append(f"BLS {spec.series_id}: {error}")

    fred = FREDAdapter()
    for spec in [item for item in FORENSIC_SERIES if item.source == "fred"]:
        result = fred.pull_series(spec.series_id, start=start, end=end)
        if not result.ok:
            errors.append(f"FRED {spec.series_id}: {result.error}")
            continue
        name = f"fred-{spec.series_id}.csv"
        raw_downloads[name] = result.raw_bytes
        downloads.append(_download_record(name, spec.source_url, result.raw_bytes))
        try:
            calculated = calculate_fact(spec, result.observations)
            fresh, warning = _fresh_enough(spec, calculated.as_of, today)
            if not fresh:
                errors.append(warning)
                continue
            facts.append({
                "spec": spec, "text": calculated.text, "as_of": calculated.as_of,
                "observations": result.observations, "raw_hash": raw_hash(result.raw_bytes),
            })
            _store_pull(result, spec, start=start, end=end, errors=errors)
        except Exception as error:
            errors.append(f"FRED {spec.series_id}: {error}")

    treasury_url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
        f"?data=daily_treasury_yield_curve&field_tdr_date_value={today.year}"
    )
    try:
        treasury_raw = fetch(treasury_url, cache_force_refresh=True).body
        name = f"treasury-daily-par-yields-{today.year}.xml"
        raw_downloads[name] = treasury_raw
        downloads.append(_download_record(name, treasury_url, treasury_raw))
        curve = parse_treasury_curve(treasury_raw)
        ordered_maturities = [label for label in TREASURY_FIELDS.values() if label in curve]
        curve_text = "; ".join(f"{label} {curve[label]:.2f}%" for label in ordered_maturities)
        treasury_spec = FactSeries(
            "treasury", "daily-par-yield-curve", "Daily Treasury par yield curve",
            "Discount and interest rates", "Percent", "Daily nominal par yields",
            "latest", 2,
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"
            f"?type=daily_treasury_yield_curve&field_tdr_date_value={today.year}",
            ("Treasury", "yield curve", "discount rate", "risk-free rate"),
        )
        if (today - Date.fromisoformat(curve["date"])).days > 10:
            raise ValueError(f"latest Treasury curve is stale: {curve['date']}")
        facts.append({
            "spec": treasury_spec,
            "text": (
                f"On {curve['date']}, the U.S. Treasury nominal par yield curve was: {curve_text}. "
                "These are market par yields by maturity, not a single legally prescribed damages discount rate."
            ),
            "as_of": curve["date"],
            "observations": [{"date": curve["date"], "value": curve.get("10-year")}],
            "raw_hash": raw_hash(treasury_raw),
        })
    except Exception as error:
        errors.append(f"Treasury yield curve: {error}")

    release_sources = [
        ("bls-ecec-current.html", "https://www.bls.gov/news.release/ecec.htm", extract_ecec_facts),
        ("bls-atus-current.html", "https://www.bls.gov/news.release/atus.htm", extract_atus_facts),
        ("bls-oews-current.html", "https://www.bls.gov/news.release/ocwage.nr0.htm", extract_oews_summary_fact),
        ("cdc-deaths-current.html", "https://www.cdc.gov/nchs/fastats/deaths.htm", extract_cdc_life_expectancy_fact),
    ]
    for name, url, extractor in release_sources:
        try:
            raw = fetch(url, cache_force_refresh=True).body
            raw_downloads[name] = raw
            downloads.append(_download_record(name, url, raw))
            extracted = extractor(raw, retrieved_at=retrieved_at)
            facts.extend(extracted if isinstance(extracted, list) else [extracted])
        except Exception as error:
            errors.append(f"{name}: {error}")

    # Preserve the current detailed files needed for case-specific calculations.
    # They are intentionally not flattened into generic facts because the right
    # occupation, sex, age, and geography are case inputs, not defaults.
    reference_downloads = [
        ("bls-oews-national-may-2025.zip", "https://www.bls.gov/oes/special-requests/oesm25nat.zip"),
        ("bls-ecec-private-2004-present.xlsx", "https://www.bls.gov/web/ecec/ecec-private-dataset.xlsx"),
        ("cdc-life-table-2023-total.xlsx", "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/NVSR/74-06/Table01.xlsx"),
        ("cdc-life-table-2023-male.xlsx", "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/NVSR/74-06/Table02.xlsx"),
        ("cdc-life-table-2023-female.xlsx", "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/NVSR/74-06/Table03.xlsx"),
    ]
    for name, url in reference_downloads:
        try:
            raw = fetch(url, cache_force_refresh=True).body
            raw_downloads[name] = raw
            downloads.append(_download_record(name, url, raw))
        except Exception as error:
            errors.append(f"{name}: {error}")

    required = {
        "CUSR0000SA0", "LNS14000000", "CES0500000003",
        "A191RL1Q225SBEA", "PCEPI", "daily-par-yield-curve",
        "ECEC-current-private", "ATUS-household-activities",
        "life-expectancy-at-birth-current",
    }
    present = {fact["spec"].series_id for fact in facts}
    missing = sorted(required - present)
    if missing:
        errors.append("Missing required corpus facts: " + ", ".join(missing))

    return materialize_corpus(
        facts=facts, raw_downloads=raw_downloads, downloads=downloads,
        errors=errors, root=root, retrieved_at=retrieved_at,
    )


def _block_id(spec: FactSeries) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", f"{spec.source}/{spec.series_id}")
    return cleaned.strip("-")[:160]


def build_deck(facts: Iterable[dict], *, retrieved_at: str) -> dict:
    blocks = []
    for item in facts:
        spec: FactSeries = item["spec"]
        observations = list(item.get("observations") or [])
        recent = observations[-14:]
        recent_text = "; ".join(
            f"{observation['date']}={observation['value']}" for observation in recent
        )
        provenance = item.get("raw_hash") or "sha256:unavailable"
        text = (
            f"{item['text']}\n\n"
            f"Units: {spec.units}. Adjustment: {spec.seasonal_adjustment}. "
            f"Recent published observations: {recent_text or '[not applicable]'}. "
            f"Retrieved {retrieved_at}. Raw response hash: {provenance}."
        )
        blocks.append({
            "id": _block_id(spec),
            "title": spec.title[:240],
            "kind": "fact",
            "text": text,
            "tags": list(dict.fromkeys((spec.category, *spec.tags)))[:32],
            "links": [],
            "source": {
                "label": f"{spec.source.upper()} — {spec.title}"[:200],
                "locator": f"Series {spec.series_id}; retrieved {retrieved_at}"[:500],
                "url": spec.source_url,
                "as_of": item["as_of"],
            },
        })
    return {
        "schema": "cueline.knowledge-deck.v1",
        "id": "econscope-forensic-economics-current",
        "title": "ECONSCOPE current forensic-economics facts",
        "description": (
            "Locally downloaded official economic facts for forensic-economics interviews and case work. "
            "Derived changes are labeled and every block carries observation and retrieval provenance."
        ),
        "created_at": retrieved_at,
        "blocks": blocks,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _markdown_corpus(facts: list[dict], retrieved_at: str, errors: list[str]) -> str:
    lines = [
        "# ECONSCOPE current forensic-economics facts",
        "",
        f"Retrieved: {retrieved_at}",
        "",
        "Derived changes below are calculated from the cited published observations and are labeled as such.",
        "",
    ]
    category = None
    for item in sorted(facts, key=lambda fact: (fact["spec"].category, fact["spec"].title)):
        spec: FactSeries = item["spec"]
        if spec.category != category:
            category = spec.category
            lines.extend([f"## {category}", ""])
        lines.extend([
            f"### {spec.title}",
            "",
            item["text"],
            "",
            f"- As of: {item['as_of']}",
            f"- Units: {spec.units}",
            f"- Adjustment: {spec.seasonal_adjustment}",
            f"- Source: [{spec.source.upper()} {spec.series_id}]({spec.source_url})",
            f"- Raw response: `{item.get('raw_hash', 'sha256:unavailable')}`",
            "",
        ])
    if errors:
        lines.extend(["## Acquisition warnings", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")
    return "\n".join(lines)


def materialize_corpus(
    *,
    facts: Iterable[dict],
    raw_downloads: dict[str, bytes],
    downloads: list[dict],
    errors: Iterable[str],
    root: Path,
    retrieved_at: str,
) -> CorpusBuildResult:
    facts = list(facts)
    errors = list(errors)
    root = Path(root)
    stamp = re.sub(r"[^0-9TZ]", "", retrieved_at)
    snapshot_dir = root / "snapshots" / stamp
    suffix = 2
    while snapshot_dir.exists():
        snapshot_dir = root / "snapshots" / f"{stamp}-{suffix}"
        suffix += 1
    raw_dir = snapshot_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)

    for name, payload in raw_downloads.items():
        safe_name = Path(name).name
        if not safe_name or safe_name != name:
            raise ValueError(f"Unsafe raw-download name: {name}")
        _atomic_write(raw_dir / safe_name, payload)

    deck = build_deck(facts, retrieved_at=retrieved_at)
    deck_bytes = (json.dumps(deck, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    markdown_bytes = _markdown_corpus(facts, retrieved_at, errors).encode("utf-8")
    sources = sorted({fact["spec"].source for fact in facts})
    manifest = {
        "schema": "econscope.forensic-corpus-manifest.v1",
        "retrieved_at": retrieved_at,
        "snapshot": snapshot_dir.name,
        "fact_count": len(facts),
        "sources": sources,
        "downloads": downloads,
        "errors": errors,
        "deck_sha256": raw_hash(deck_bytes),
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    _atomic_write(snapshot_dir / "cueline-deck.json", deck_bytes)
    _atomic_write(snapshot_dir / "facts.md", markdown_bytes)
    _atomic_write(snapshot_dir / "manifest.json", manifest_bytes)

    deck_path = root / "cueline-current.json"
    markdown_path = root / "facts-current.md"
    manifest_path = root / "manifest-current.json"
    _atomic_write(deck_path, deck_bytes)
    _atomic_write(markdown_path, markdown_bytes)
    _atomic_write(manifest_path, manifest_bytes)

    return CorpusBuildResult(
        root=root,
        snapshot_dir=snapshot_dir,
        deck_path=deck_path,
        markdown_path=markdown_path,
        manifest_path=manifest_path,
        fact_count=len(facts),
        errors=tuple(errors),
    )
