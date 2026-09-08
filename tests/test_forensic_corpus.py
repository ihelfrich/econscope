"""Unit contract for the local Cueline forensic-economics fact corpus."""

from __future__ import annotations

import json

from econscope.corpus.forensic_economics import (
    FORENSIC_SERIES,
    FactSeries,
    build_deck,
    calculate_fact,
    extract_atus_facts,
    extract_ecec_facts,
    materialize_corpus,
    parse_treasury_curve,
)


def spec(**overrides):
    values = {
        "source": "bls",
        "series_id": "CUSR0000SA0",
        "title": "Consumer Price Index for All Urban Consumers",
        "category": "Inflation and escalation",
        "units": "Index 1982-84=100",
        "seasonal_adjustment": "Seasonally adjusted",
        "transform": "latest_and_yoy_percent",
        "decimals": 1,
        "source_url": "https://data.bls.gov/timeseries/CUSR0000SA0",
        "tags": ("CPI", "inflation", "escalation"),
    }
    values.update(overrides)
    return FactSeries(**values)


def test_latest_and_yoy_fact_labels_the_calculation():
    observations = [
        {"date": "2025-07-01", "value": 320.0},
        {"date": "2026-06-01", "value": 329.0},
        {"date": "2026-07-01", "value": 330.88},
    ]
    fact = calculate_fact(spec(), observations)
    assert fact.as_of == "2026-07-01"
    assert fact.value == 330.88
    assert fact.change == 3.4
    assert "3.4%" in fact.text
    assert "calculated from the published index levels" in fact.text


def test_percentage_point_change_is_not_mislabeled_as_percent_growth():
    observations = [
        {"date": "2025-07-01", "value": 4.1},
        {"date": "2026-07-01", "value": 4.3},
    ]
    fact = calculate_fact(spec(
        series_id="LNS14000000",
        title="Unemployment rate",
        units="Percent",
        transform="latest_and_yoy_points",
    ), observations)
    assert "4.3%" in fact.text
    assert "+0.2 percentage points" in fact.text
    assert "0.2%" not in fact.text


def test_treasury_xml_parser_keeps_the_latest_complete_curve():
    raw = b'''<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
          xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE m:type="Edm.DateTime">2026-08-17T00:00:00</d:NEW_DATE>
        <d:BC_3MONTH m:type="Edm.Double">4.05</d:BC_3MONTH>
        <d:BC_2YEAR m:type="Edm.Double">3.88</d:BC_2YEAR>
        <d:BC_10YEAR m:type="Edm.Double">4.31</d:BC_10YEAR>
      </m:properties></content></entry>
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE m:type="Edm.DateTime">2026-08-18T00:00:00</d:NEW_DATE>
        <d:BC_3MONTH m:type="Edm.Double">4.04</d:BC_3MONTH>
        <d:BC_2YEAR m:type="Edm.Double">3.90</d:BC_2YEAR>
        <d:BC_10YEAR m:type="Edm.Double">4.33</d:BC_10YEAR>
      </m:properties></content></entry>
    </feed>'''
    curve = parse_treasury_curve(raw)
    assert curve["date"] == "2026-08-18"
    assert curve["3-month"] == 4.04
    assert curve["2-year"] == 3.90
    assert curve["10-year"] == 4.33


def test_deck_is_cueline_schema_with_direct_provenance():
    facts = [{
        "spec": spec(),
        "text": "In July 2026, CPI was 330.9; its 12-month change was 3.4%.",
        "as_of": "2026-07-01",
        "observations": [
            {"date": "2025-07-01", "value": 320.0},
            {"date": "2026-07-01", "value": 330.88},
        ],
        "raw_hash": "sha256:" + "a" * 64,
    }]
    deck = build_deck(facts, retrieved_at="2026-08-19T15:30:00Z")

    assert deck["schema"] == "cueline.knowledge-deck.v1"
    assert deck["created_at"] == "2026-08-19T15:30:00Z"
    assert len(deck["blocks"]) == 1
    block = deck["blocks"][0]
    assert block["kind"] == "fact"
    assert block["source"]["url"].startswith("https://")
    assert block["source"]["as_of"] == "2026-07-01"
    assert "sha256:" in block["text"]
    json.dumps(deck)


def test_catalog_covers_the_core_forensic_economics_inputs():
    categories = {item.category for item in FORENSIC_SERIES}
    ids = {item.series_id for item in FORENSIC_SERIES}
    assert {
        "Inflation and escalation",
        "Labor market and earnings",
        "Macroeconomic income and growth",
    }.issubset(categories)
    assert {"CUSR0000SA0", "LNS14000000", "CES0500000003"}.issubset(ids)
    assert {"PCEPI", "A191RL1Q225SBEA", "FEDFUNDS"}.issubset(ids)
    assert len([item for item in FORENSIC_SERIES if item.source == "bls"]) <= 25


def test_ecec_release_extractor_keeps_cost_and_share_distinct():
    html = b"""
    <h1>EMPLOYER COSTS FOR EMPLOYEE COMPENSATION - MARCH 2026</h1>
    <p>Employer costs for employee compensation for civilian workers averaged $49.32 per hour worked in
    March 2026. Wages and salaries averaged $33.72, while benefit costs averaged $15.60.</p>
    <p>Total employer compensation costs for private industry workers averaged $46.60 per hour worked.
    Wages and salaries averaged $32.60 per hour worked and accounted for 69.9 percent of employer costs,
    while benefit costs averaged $14.01 per hour worked and accounted for the remaining 30.1 percent.</p>
    """
    facts = extract_ecec_facts(html, retrieved_at="2026-08-19T15:30:00Z")
    assert len(facts) == 2
    assert facts[0]["as_of"] == "2026-03-01"
    assert "$49.32 per hour" in facts[0]["text"]
    assert "$15.60" in facts[0]["text"]
    assert "30.1%" in facts[1]["text"]


def test_atus_release_extractor_preserves_population_definitions():
    html = b"""
    <h1>AMERICAN TIME USE SURVEY - 2025 RESULTS</h1>
    <table>
      <tr><td>Household activities</td><td>1.99</td><td>1.58</td><td>2.38</td>
          <td>80.9</td><td>74.9</td><td>86.7</td></tr>
    </table>
    <p>Child under age 6</p>
    <table><tr><td>Caring for household children as a primary activity</td>
      <td>2.30</td><td>1.70</td><td>2.82</td></tr></table>
    """
    facts = extract_atus_facts(html, retrieved_at="2026-08-19T15:30:00Z")
    assert len(facts) == 2
    assert facts[0]["as_of"] == "2025-01-01"
    assert "people age 15 and over" in facts[0]["text"]
    assert "1.99 hours" in facts[0]["text"]
    assert "households with a child under age 6" in facts[1]["text"]
    assert "2.30 hours" in facts[1]["text"]


def test_materialize_corpus_keeps_versioned_raw_data_and_stable_cueline_path(tmp_path):
    fact = calculate_fact(spec(), [
        {"date": "2025-07-01", "value": 320.0},
        {"date": "2026-07-01", "value": 330.88},
    ])
    facts = [{
        "spec": spec(),
        "text": fact.text,
        "as_of": fact.as_of,
        "observations": [
            {"date": "2025-07-01", "value": 320.0},
            {"date": "2026-07-01", "value": 330.88},
        ],
        "raw_hash": "sha256:" + "a" * 64,
    }]
    result = materialize_corpus(
        facts=facts,
        raw_downloads={"bls-timeseries.json": b'{"status":"REQUEST_SUCCEEDED"}'},
        downloads=[{
            "file": "bls-timeseries.json",
            "url": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            "bytes": 30,
            "sha256": "sha256:" + "b" * 64,
        }],
        errors=[],
        root=tmp_path,
        retrieved_at="2026-08-19T15:30:00Z",
    )

    assert result.deck_path == tmp_path / "cueline-current.json"
    assert result.deck_path.is_file()
    assert result.markdown_path.is_file()
    assert result.manifest_path.is_file()
    assert result.snapshot_dir.name == "20260819T153000Z"
    assert (result.snapshot_dir / "raw" / "bls-timeseries.json").read_bytes().startswith(b'{')
    assert json.loads(result.deck_path.read_text())["blocks"][0]["source"]["as_of"] == "2026-07-01"
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["fact_count"] == 1
    assert manifest["errors"] == []
