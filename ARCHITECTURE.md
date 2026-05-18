# ECONSCOPE: Development Architecture

**Working title.** The product name, visual identity, and brand are TBD (see Phase 7).

**Author:** Dr. Ian Helfrich
**Co-architect (spatial/econometric core):** Dr. Elizaveta Gonchar
**Date:** 2026-05-18
**Status:** Architecture draft v1

---

## What this is

A unified economic intelligence platform that can, given a company, sector, country, person, or policy question, produce an exhaustive, source-verified, reproducible analytical report that integrates financial forensics, network analysis, geospatial intelligence, macro/micro economic modeling, legal/regulatory research, and institutional report synthesis.

Each analysis enriches a persistent knowledge graph. The system gets smarter with every run.

The analogy: Kali Linux is a penetration-testing distribution — hundreds of specialized tools, organized by attack phase, with a unified interface. This is that, but for economic and financial research. Every tool has a specific job. The platform orchestrates them.

---

## Existing arsenal (already built, working)

These tools are operational and become subsystems of the platform:

| Tool | Language | What it does | Subsystem role |
|---|---|---|---|
| **web-intel** | Go | Parallel web crawler, 2,300 URL/s, JSONL + HTML archive | Crawl engine |
| **forensic-econ** | Go | SEC EDGAR/XBRL, Beneish/Altman/Sloan, Wayback, OSINT | Financial forensics |
| **company-dissector** | JS/Electron | 12-tab company profiling GUI (SEC, GDELT, patents, courts, sanctions) | Existing GUI (to be absorbed) |
| **deepwire** | Python | Connection discovery: EDGAR FTS, Wikidata, GDELT, Reddit, networkx | Network intelligence |
| **groundtruth** | Python | Property intelligence: NYC PLUTO/ACRIS, UK Land Registry, Companies House | Real asset layer |
| **GodsEye** | Rust | AIS/ADS-B/satellite/news ingest + geo + ML (in development) | Physical-world intelligence |
| **Topology Engine** | Python | Spatial autoregression, structural gravity, labor market topology | Econometric core |
| **Shadow_Scraper** | Python | Web scraping framework | Auxiliary crawl |
| **MacroPulse** | Python/JS | Macro dashboard (frontend + backend) | Dashboard prototype |
| **Helfrich_Quant_Platform** | TS/Vite | Quantitative webapp | UI prototype |
| **build-corpus** | Claude skill | Swarm-based research corpus builder | Corpus assembly |

---

## System architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LAYER 7: INTERFACE                                 │
│                                                                             │
│  ┌──────────┐  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   CLI    │  │  Electron Hub  │  │ GitHub Pages │  │  Notifications   │  │
│  │ (primary)│  │ (local GUI)    │  │ (catalog +   │  │ (macOS, iMsg,   │  │
│  │          │  │                │  │  reports)    │  │  Pushover)       │  │
│  └──────────┘  └────────────────┘  └──────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                       LAYER 6: REPORT ENGINE                                │
│                                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Template     │  │ Chart/Figure  │  │ Visual       │  │ Export       │  │
│  │ System       │  │ Generator     │  │ Identity     │  │ (PDF, HTML,  │  │
│  │ (LaTeX +     │  │ (matplotlib,  │  │ (palette,    │  │  DOCX, PPT,  │  │
│  │  Quarto)     │  │  D3, Kepler)  │  │  type, grid) │  │  JSON)       │  │
│  └──────────────┘  └───────────────┘  └──────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                    LAYER 5: INTELLIGENCE ENGINE                              │
│                                                                             │
│  ┌────────────────┐  ┌───────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ Cross-ref      │  │ Anomaly       │  │ Knowledge    │  │ Audit      │  │
│  │ Engine         │  │ Detection     │  │ Accumulator  │  │ Engine     │  │
│  │ (entity        │  │ (statistical  │  │ (each run    │  │ (local,    │  │
│  │  resolution,   │  │  outliers,    │  │  enriches    │  │  global,   │  │
│  │  dedup,        │  │  Benford,     │  │  the graph)  │  │  super-    │  │
│  │  reconcile)    │  │  forensic)    │  │              │  │  global)   │  │
│  └────────────────┘  └───────────────┘  └──────────────┘  └────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                     LAYER 4: ANALYSIS ENGINES                               │
│                                                                             │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │Financial │ │ Network   │ │Geospatial│ │ Macro/   │ │ Legal/         │  │
│  │Forensics │ │ Analysis  │ │ Intel    │ │ Sector   │ │ Regulatory     │  │
│  │          │ │           │ │          │ │          │ │                │  │
│  │Beneish   │ │Centrality │ │Spatial   │ │DSGE      │ │Court dockets  │  │
│  │Altman Z  │ │Community  │ │autocorr  │ │Gravity   │ │Sanctions      │  │
│  │Sloan     │ │Brokerage  │ │OT dist   │ │IO tables │ │Regulatory     │  │
│  │Piotroski │ │Contagion  │ │Clustering│ │VAR/SVAR  │ │filings        │  │
│  │DuPont    │ │Influence  │ │HH survey │ │Panel FE  │ │Patent claims  │  │
│  │FCF qual  │ │k-hop path │ │Nightlight│ │Forecast  │ │Enforcement    │  │
│  └──────────┘ └───────────┘ └──────────┘ └──────────┘ └────────────────┘  │
│                                                                             │
│  Existing tools:  forensic-econ ──► Financial Forensics                     │
│                   deepwire ──────► Network Analysis                         │
│                   groundtruth ───► Geospatial Intel (property subset)       │
│                   Topology Engine ► Macro/Sector (spatial econ subset)       │
│                   GodsEye ───────► Geospatial Intel (physical world)        │
├─────────────────────────────────────────────────────────────────────────────┤
│                    LAYER 3: STORAGE + KNOWLEDGE GRAPH                       │
│                                                                             │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────────────────┐  │
│  │   DuckDB           │  │  Knowledge Graph    │  │  Document Store      │  │
│  │   Warehouse        │  │  (Neo4j or          │  │  (JSONL + SHA1       │  │
│  │                    │  │   SQLite-backed      │  │   HTML archive)      │  │
│  │ Time series        │  │   networkx)          │  │                      │  │
│  │ Financial stmts    │  │                      │  │ SEC filings          │  │
│  │ Economic indicators│  │ Entities (firms,     │  │ Institutional rpts   │  │
│  │ Trade flows        │  │   people, orgs)      │  │ Court documents      │  │
│  │ Survey data        │  │ Relationships        │  │ News articles        │  │
│  │ Audit trail        │  │ Events               │  │ Academic papers      │  │
│  │ Job manifests      │  │ Ownership chains     │  │ Crawl archives       │  │
│  │                    │  │ Board interlocks      │  │                      │  │
│  │ Provenance:        │  │ Financial flows       │  │ Full-text search     │  │
│  │  source, series,   │  │ Legal proceedings     │  │ via tantivy or       │  │
│  │  pull_ts, hash     │  │ Geographic links      │  │ sqlite FTS5          │  │
│  └────────────────────┘  └────────────────────┘  └──────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                   LAYER 2: PARSE + EXTRACT + ENRICH                         │
│                                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Document     │  │ Entity        │  │ Financial    │  │ Geospatial   │  │
│  │ Parser       │  │ Extractor     │  │ Extractor    │  │ Extractor    │  │
│  │              │  │               │  │              │  │              │  │
│  │ GROBID (PDF) │  │ spaCy NER     │  │ XBRL parser  │  │ Address      │  │
│  │ pdfplumber   │  │ nomenklatura  │  │ Table detect │  │ resolution   │  │
│  │ python-docx  │  │ (entity       │  │ Ratio calc   │  │ Geocoding    │  │
│  │ BeautifulSoup│  │  resolution)  │  │ Unit normal  │  │ Coord extract│  │
│  │ Tika (fallbk)│  │ OpenFIGI      │  │ Currency     │  │ Boundary     │  │
│  │              │  │ (instrument   │  │ normalize    │  │ matching     │  │
│  │              │  │  linking)     │  │              │  │              │  │
│  └──────────────┘  └───────────────┘  └──────────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                    LAYER 1: DATA ACQUISITION                                │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      RATE GOVERNOR + BATCH SCHEDULER                  │  │
│  │                                                                       │  │
│  │  Per-source rate limits  ·  Parallel streams across sources           │  │
│  │  Adaptive pacing         ·  Persistent job queue (SQLite)             │  │
│  │  Resume from failure     ·  Progress notifications                    │  │
│  │  Job manifests           ·  Checkpointing                             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─── API Adapters ──────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  MACRO/ECONOMIC          FINANCIAL/CORPORATE       LEGAL/REGULATORY   │  │
│  │  ├─ FRED (800K series)   ├─ SEC EDGAR (EFTS+XBRL)  ├─ CourtListener  │  │
│  │  ├─ BLS (CPI,empl,wage)  ├─ Finnhub (quotes,ESG)   ├─ OpenSanctions  │  │
│  │  ├─ BEA (GDP,PCE,IO)     ├─ Fin.Model.Prep (fund)  ├─ PACER/RECAP   │  │
│  │  ├─ Census (ACS,CBP)     ├─ Yahoo Finance (hist)    ├─ OpenCorporates │  │
│  │  ├─ Treasury (fiscal)    ├─ Polygon.io (tick)       ├─ USPTO Patents  │  │
│  │  ├─ DBnomics (70+ prov)  ├─ OpenFIGI (identifiers)  ├─ FDA (drugs)   │  │
│  │  ├─ IMF (WEO,IFS,DOTS)   ├─ Crunchbase (startups)   ├─ FCC           │  │
│  │  ├─ World Bank (WDI)     ├─ LittleSis (power map)   ├─ CFPB          │  │
│  │  ├─ OECD (STAN,MEI)      ├─ Wikidata (structured)   │                │  │
│  │  ├─ Eurostat             ├─ FDIC (bank financials)   │                │  │
│  │  ├─ ECB (SDW)            ├─ CFTC (COT positioning)   │                │  │
│  │  ├─ UK ONS               │                           │                │  │
│  │  ├─ Bank of England      │  GEOSPATIAL               │                │  │
│  │  ├─ EIA (energy)         │  ├─ WorldPop (pop grids)  │                │  │
│  │  ├─ USDA (agriculture)   │  ├─ GHS-SMOD (settlement) │                │  │
│  │  ├─ FHFA (house prices)  │  ├─ VIIRS (nightlights)  │                │  │
│  │  ├─ ILO (labor)          │  ├─ OpenStreetMap         │                │  │
│  │  ├─ UN Comtrade (trade)  │  ├─ NYC/UK property       │                │  │
│  │  ├─ UNCTAD (FDI)         │  ├─ Kepler.gl (viz)       │                │  │
│  │  ├─ SIPRI (military)     │  ├─ AIS/ADS-B (GodsEye)  │                │  │
│  │  ├─ Penn World Table     │  └─ Sentinel/Landsat      │                │  │
│  │  └─ Maddison (hist GDP)  │                           │                │  │
│  │                                                                       │  │
│  │  ACADEMIC/INSTITUTIONAL  CRAWL TARGETS (via web-intel)                │  │
│  │  ├─ OpenAlex (papers)    ├─ McKinsey Global Institute                 │  │
│  │  ├─ Semantic Scholar     ├─ Bain / BCG / Deloitte / PwC / EY         │  │
│  │  ├─ NBER (working ppr)   ├─ BIS Quarterly Review                     │  │
│  │  ├─ SSRN                 ├─ 12 Federal Reserve Banks                  │  │
│  │  ├─ arXiv (econ)         ├─ Peterson / Brookings / PIIE              │  │
│  │  └─ Google Scholar       ├─ Reuters / Bloomberg News / FT             │  │
│  │                          ├─ Sector-specific (per-target)              │  │
│  │                          └─ Wayback Machine (historical)              │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Existing tools:  web-intel ────────► Crawl engine                          │
│                   forensic-econ ───► EDGAR + OSINT adapters                 │
│                   deepwire ────────► EDGAR FTS + Wikidata + GDELT + Reddit  │
│                   groundtruth ─────► NYC/UK property adapters               │
│                   GodsEye ─────────► AIS/ADS-B/satellite ingest             │
│                   Shadow_Scraper ──► Auxiliary scraping                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Analysis modes

The platform operates in five modes, each composing different layers:

### Mode 1: COMPANY (firm-level intelligence)

Input: company name, ticker, or CIK

Produces:
- Complete financial forensics (7 years of statements, 6+ scoring models)
- Board/executive network map (who they know, who they're connected to, shared board seats)
- Personal dossiers on key decision-makers (public records, filings, Wikidata, LittleSis)
- Regulatory exposure (every SEC filing, court docket, enforcement action, patent dispute)
- Property/asset footprint (real estate, subsidiary structure, geographic exposure)
- Competitive positioning (sector comparison, market share, relative valuation)
- Institutional report synthesis (what McKinsey/Bain/sell-side analysts have said)
- News sentiment timeline (GDELT + crawled coverage)
- Supply chain / trade network position (Comtrade + BACI + firm disclosures)
- Macro exposure assessment (which economic factors hit this firm hardest)

Enriches the knowledge graph with: all entities discovered, all relationships, all financials.

### Mode 2: SECTOR (industry-level analysis)

Input: NAICS/GICS code, or a natural-language sector description

Produces:
- All companies in sector (via EDGAR SIC, Compustat, or NAICS lookup)
- Sector-wide financial benchmarks (median ratios, growth rates, margins)
- Concentration analysis (HHI, CR4, market structure)
- Regulatory landscape (sector-specific agencies, recent enforcement trends)
- Labor market analysis (BLS occupation data, wage trends, JOLTS for sector)
- Trade exposure (import competition, export dependence, tariff vulnerability)
- Cross-sector network (which firms bridge multiple sectors, conglomerate mapping)

### Mode 3: PERSON (individual intelligence)

Input: person name + affiliation hint

Produces:
- Board seats and executive positions (EDGAR, OpenCorporates, Companies House)
- Ownership stakes (13D/13G filings, beneficial ownership)
- Political connections (LittleSis, FEC donations, lobbying disclosures)
- Legal history (CourtListener, sanctions, enforcement)
- Wikidata structured profile
- Network map (k-hop connections to other entities in the knowledge graph)
- Property holdings (groundtruth, where data is available)
- Published works / patents (OpenAlex, USPTO)
- Media footprint (GDELT, news crawl)

### Mode 4: MACRO (economic environment analysis)

Input: country, region, or thematic question (e.g., "US consumer credit conditions 2024")

Produces:
- Multi-source indicator dashboard (FRED, BLS, BEA, IMF, World Bank, central banks)
- Time series analysis (trend decomposition, structural breaks, forecasts)
- Spatial analysis (regional variation, metro-level, county-level where available)
- Trade position (bilateral flows, revealed comparative advantage, GVC participation)
- Policy environment (central bank statements, fiscal policy, regulatory changes)
- Distributional analysis (by income quintile, education, race, age — where data exists)
- International comparison (peer countries, convergence/divergence)

### Mode 5: NETWORK (relationship and influence mapping)

Input: two or more entities (companies, people, countries)

Produces:
- Shortest path / all paths between entities in knowledge graph
- Common connections (shared board members, shared investors, shared law firms)
- Financial flows between entities
- Co-occurrence in filings, news, and legal proceedings
- Influence metrics (betweenness centrality, brokerage scores)
- Temporal evolution (how the relationship changed over time)
- Visualization (force-directed graph, Sankey flows, geographic overlay)

---

## Data acquisition: the rate-governed batch system

### Research targets

A research target is a declarative specification of data needed:

```yaml
# Example: pull all county-level employment data
target:
  name: "BLS county employment 2015-2024"
  source: bls_v2
  series_pattern: "LAUCN*"
  geography: all_counties
  start: 2015-01-01
  end: 2024-12-31
  priority: normal        # normal | high | background
  notify: [macos, imessage]
```

### Execution pipeline

```
Target definition
       │
       ▼
┌──────────────┐
│  SCOPING     │  Hit metadata endpoints (not rate-limited)
│  QUERY       │  Count series, estimate records, check cache
│              │  Report: "12,972 series, ~1.5M records, ~10 min"
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  PLAN        │  Choose batch strategy per source
│  GENERATION  │  Calculate optimal request pacing
│              │  Identify parallelizable streams
│              │  Estimate wall-clock time
│              │  User confirms or adjusts
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  EXECUTION   │  Per-source rate governor enforces limits
│  ENGINE      │  Parallel streams across independent sources
│              │  Each completed batch → DuckDB immediately
│              │  Checkpoint every N requests to job state file
│              │  Adaptive pacing: start 80% max, creep up, back off on 429
│              │  Retry with exponential backoff on transient errors
│              │  Resume from last checkpoint on restart
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  VALIDATION  │  Record counts match expected
│  + MANIFEST  │  No gaps in date ranges
│              │  Hash all pulled data
│              │  Write job manifest (YAML)
│              │  Trigger notifications
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  ENRICHMENT  │  Run Layer 2 extractors on new data
│  TRIGGER     │  Update knowledge graph with new entities
│              │  Flag anomalies for review
└──────────────┘
```

### Rate limit registry

```yaml
rate_limits:
  fred:
    requests_per_minute: 120
    daily_cap: null
    batch_size: 1  # one series per request, but up to 100K obs
    strategy: burst
    
  bls_v2:
    requests_per_day: 500
    batch_size: 50  # series per request
    strategy: batch_maximize
    
  bea:
    requests_per_minute: 100
    daily_cap: 1000
    batch_size: 1
    strategy: sustained
    
  census:
    requests_per_day: 500
    batch_size: 50  # variables per request
    strategy: batch_maximize
    
  edgar_efts:
    requests_per_second: 10
    daily_cap: null
    batch_size: 1
    strategy: burst
    
  finnhub:
    requests_per_minute: 60
    daily_cap: null
    batch_size: 1
    strategy: sustained
    
  dbnomics:
    requests_per_second: 5  # self-imposed politeness
    daily_cap: null
    batch_size: 100  # series per request
    strategy: polite_burst
    
  world_bank:
    requests_per_second: 2  # self-imposed
    daily_cap: null
    batch_size: 1
    strategy: polite
    
  web_intel:  # internal crawler
    requests_per_second: 10  # per domain, configurable
    daily_cap: null
    strategy: domain_distributed
```

### Multi-target research plans

```yaml
# Research plan: comprehensive Soho House analysis
plan:
  name: "Soho House deep dive"
  mode: company
  target_entity: "Soho House & Co Inc"
  cik: "0001846510"
  ticker: "SHCO"
  
  targets:
    - name: edgar_filings
      source: edgar
      params: { cik: "0001846510", types: [10-K, 10-Q, 8-K, S-1, DEF14A, SC13E3] }
      
    - name: macro_context
      source: [fred, bls, bea]
      params:
        fred: [PSAVERT, FEDFUNDS, CPIAUCSL, DRTSCILM, TOTALSL, REVOLSL]
        bls: [CES7000000001, CEU7072000001]  # leisure/hospitality employment
        bea: [T20305, T20100]  # PCE by category
        
    - name: network_discovery
      source: deepwire
      params: { entity: "Soho House", hops: 2 }
      
    - name: property_footprint
      source: groundtruth
      params: { addresses: [from_10K_extract] }
      
    - name: institutional_reports
      source: web_intel
      params:
        domains: [moodys.com, spglobal.com, reuters.com, ft.com, bloomberg.com]
        query: "Soho House"
        
    - name: court_regulatory
      source: [courtlistener, opensanctions]
      params: { entity: "Soho House" }
      
    - name: academic_coverage
      source: [openalex, semantic_scholar]
      params: { query: "membership clubs luxury hospitality economics" }
      
    - name: competitor_scan
      source: edgar
      params: { sic: 7941, types: [10-K] }  # membership sports/rec clubs
      
  execution:
    parallel: true  # all targets run simultaneously
    estimated_time: "~45 minutes (bottleneck: web-intel crawl)"
    notify: [macos, imessage]
    on_complete: trigger_analysis
```

---

## The knowledge graph schema

Every entity, relationship, and event discovered by any analysis mode gets deposited here.

### Node types

```
COMPANY     { cik, ticker, name, sic, country, founded, status }
PERSON      { name, roles[], affiliations[], wikidata_id }
GOVERNMENT  { name, jurisdiction, type: [agency|legislature|court] }
SECURITY    { figi, isin, cusip, type: [equity|debt|derivative] }
PROPERTY    { address, bbl, coordinates, type, assessed_value }
PATENT      { number, title, date, cpc_class }
CASE        { docket, court, parties[], status }
DOCUMENT    { source, type, date, hash, path_in_store }
INDICATOR   { source, series_id, description, frequency, geography }
SECTOR      { code, system: [naics|gics|sic], description }
COUNTRY     { iso3, name, region, income_group }
EVENT       { type, date, entities[], description, source_doc }
```

### Edge types

```
OFFICER_OF          person → company   { role, start, end }
BOARD_MEMBER_OF     person → company   { start, end, committee }
OWNS_SHARES_IN      entity → company   { shares, pct, filing_date, source }
SUBSIDIARY_OF       company → company  { pct_owned, jurisdiction }
SUPPLIES_TO         company → company  { product, value, source }
COMPETES_WITH       company → company  { sector, overlap_score }
FILED_IN            company → case     { role: [plaintiff|defendant] }
SANCTIONED          entity → entity    { program, date, source }
LOCATED_AT          entity → property  { type: [hq|branch|warehouse] }
HOLDS_PATENT        entity → patent    { type: [assignee|inventor] }
ISSUED_SECURITY     company → security { date, amount, terms }
OPERATES_IN         company → country  { revenue_pct, segment }
CONNECTED_TO        entity → entity    { type, strength, path_length, source }
CITES               document → document
MENTIONS            document → entity
MEASURED_BY         entity → indicator { value, date }
```

### Graph operations

- **Shortest path**: find the connection chain between any two entities
- **Common neighbors**: shared board members, shared investors, shared counsel
- **Community detection**: Louvain/Leiden clustering of corporate ecosystems
- **Centrality ranking**: betweenness, eigenvector, PageRank across the full graph
- **Temporal evolution**: how the graph changed over time (edge additions/deletions)
- **Subgraph extraction**: pull the relevant neighborhood for a specific analysis
- **Anomaly detection**: unusually dense connections, sudden relationship changes

---

## The audit engine (local / global / super-global)

### Local audit (per-computation)

Every data pull and every computation logs:

```json
{
  "audit_id": "a-20260518-143022-fred-psavert",
  "level": "local",
  "operation": "pull",
  "source": "fred",
  "series_id": "PSAVERT",
  "params": { "start": "2019-01-01", "end": "2024-12-31" },
  "timestamp": "2026-05-18T14:30:22Z",
  "records_returned": 72,
  "last_observation": "2024-12-01",
  "value_at_last": 3.8,
  "response_hash": "sha256:7f2a...",
  "cached": false,
  "assertions_passed": [
    "record_count == expected (72)",
    "no_null_values",
    "date_range_complete",
    "values_within_historical_bounds (0-40%)"
  ]
}
```

Every derived statistic includes:

```json
{
  "audit_id": "a-20260518-143025-calc-savings-decline",
  "level": "local",
  "operation": "compute",
  "description": "Personal savings rate decline from COVID peak",
  "formula": "PSAVERT[2020-04] - PSAVERT[2024-12]",
  "inputs": ["a-20260518-143022-fred-psavert"],
  "result": 30.0,
  "unit": "percentage_points",
  "assertion": "result > 0 (savings rate did decline)"
}
```

### Global audit (per-project)

After all sections of a report are generated, the audit engine:

1. **Cross-references all cited numbers** against their audit trails
2. **Checks internal consistency**: if Section 1 says GDP grew 2.5% and Section 4 says the economy contracted, flag it
3. **Verifies temporal consistency**: all data points from the same reference period
4. **Checks source diversity**: flags sections that rely on a single source
5. **Validates citations**: every number traces to a named source with a pull record

Output: a consistency report appended to the project manifest.

### Super-global audit (across all projects)

Compares the current analysis against:

1. **The knowledge graph**: does this firm's leverage ratio look normal for its sector? (requires prior sector analyses)
2. **Macro benchmarks**: is the savings rate cited here consistent with what we used in 3 other reports this month?
3. **Historical analyses**: if we analyzed this company 6 months ago, what changed? Flag any reversals or contradictions.
4. **Staleness detection**: flag any data point older than its source's update frequency (e.g., using a monthly series that hasn't been refreshed in 60 days)

---

## API key registry

### Required (get these first)

| API | Registration URL | Key env var | Priority |
|---|---|---|---|
| FRED | research.stlouisfed.org/useraccount/apikeys | `FRED_API_KEY` | P0 |
| BLS | bls.gov/developers/ | `BLS_API_KEY` | P0 |
| BEA | apps.bea.gov/API/signup/ | `BEA_API_KEY` | P0 |
| Census | census.gov/developers/ | `CENSUS_API_KEY` | P1 |
| EIA | eia.gov/opendata/ | `EIA_API_KEY` | P1 |
| UK Companies House | developer.company-information.service.gov.uk | `COMPANIES_HOUSE_KEY` | P1 |

### Recommended (free, enhance capabilities)

| API | Registration URL | Key env var | Priority |
|---|---|---|---|
| Finnhub | finnhub.io/register | `FINNHUB_API_KEY` | P2 |
| Alpha Vantage | alphavantage.co/support/ | `ALPHA_VANTAGE_KEY` | P2 |
| Financial Modeling Prep | financialmodelingprep.com/developer | `FMP_API_KEY` | P2 |
| Polygon.io | polygon.io/dashboard/signup | `POLYGON_API_KEY` | P2 |
| OpenCorporates | opencorporates.com/api_accounts/new | `OPENCORPORATES_API_TOKEN` | P2 |
| OpenSanctions | opensanctions.org/api/ | `OPENSANCTIONS_API_KEY` | P2 |
| CourtListener | courtlistener.com/api/rest-info/ | `COURTLISTENER_API_TOKEN` | P2 |
| Pushover (notifications) | pushover.net | `PUSHOVER_USER_KEY` | P3 |

### No key needed (ready now)

SEC EDGAR, DBnomics, IMF, World Bank, OECD, Eurostat, ECB, Bank of England,
UK ONS, Treasury FiscalData, FHFA, CFTC, CFPB, FDIC, OpenAlex, Semantic Scholar,
Wikidata, GDELT, USPTO PatentsView, UN Comtrade (limited), Penn World Table,
Maddison Project, SIPRI, ILO.

---

## Technology stack

### Core platform

| Component | Technology | Rationale |
|---|---|---|
| CLI framework | Python (click or typer) | Most adapters are Python; some shell out to Go binaries |
| API adapters | Python (httpx async) | Async HTTP for parallel streams within rate limits |
| Rate governor | Python (asyncio + token bucket) | Fine-grained per-source pacing |
| Job scheduler | SQLite + Python | Persistent job queue, survives restarts |
| Data warehouse | DuckDB | Columnar, fast analytical queries, single-file, no server |
| Knowledge graph | SQLite + FTS5 + networkx | Start simple; migrate to Neo4j if graph exceeds ~10M edges |
| Document store | Filesystem (SHA1-sharded) + SQLite index | Matches web-intel's existing pattern |
| Full-text search | SQLite FTS5 or tantivy (Rust) | FTS5 for simplicity; tantivy if performance demands it |
| Financial parsing | XBRL via existing forensic-econ | Go binary, called from Python |
| PDF extraction | GROBID + pdfplumber | GROBID for academic; pdfplumber for financial |
| Entity resolution | nomenklatura + spaCy | Deduplicate across sources |
| Web crawling | web-intel (Go binary) | Already built, fast |
| Network analysis | networkx + igraph (for large graphs) | deepwire already uses networkx |
| Geospatial | geopandas + rasterio + Kepler.gl | Existing stack |

### Report generation

| Component | Technology | Rationale |
|---|---|---|
| PDF reports | XeLaTeX (via templates) | Full typographic control, brand palette |
| HTML reports | Quarto | Dual output, interactive charts |
| Charts | matplotlib (static) + D3.js (interactive) | matplotlib for PDF, D3 for web |
| Maps | Kepler.gl + Leaflet | Large-scale viz + lightweight embeds |
| Slide decks | Quarto revealjs or LaTeX beamer | From same source as reports |

### Interface

| Component | Technology | Rationale |
|---|---|---|
| CLI | Python (typer) | Primary interface for power users |
| Electron hub | Electron + vanilla JS | Extends company-dissector pattern |
| GitHub Pages | Static HTML + client-side JS | Catalog browser, published reports |
| Notifications | macOS NSUserNotification + iMessage + Pushover | Multi-channel |

### Infrastructure

| Component | Technology | Rationale |
|---|---|---|
| Package management | uv (Python) | Fast, replaces pip+venv |
| Task runner | make or just | Cross-platform, no dependencies |
| Testing | pytest + hypothesis | Property-based testing for data transforms |
| CI | GitHub Actions | Catalog rebuild, test suite, Pages deploy |
| Secrets | .env files (python-dotenv) | Never committed; per-environment |

---

## Build phases

### Phase 1: Foundation (week 1-2)

**Goal:** Pull real data from 6 sources via CLI, store in DuckDB with full audit trail.

Deliverables:
- [ ] Project scaffolding: `~/Projects/econscope/` with `pyproject.toml`, `Makefile`, `.env.example`
- [ ] Adapter interface: base class that all source adapters implement
- [ ] Rate governor: token-bucket async rate limiter with per-source config
- [ ] DuckDB warehouse: schema for time series, audit log, job manifests
- [ ] Adapters: FRED, BLS, BEA, SEC EDGAR, DBnomics, Treasury FiscalData
- [ ] CLI: `econscope pull`, `econscope search`, `econscope status`
- [ ] Job system: persistent queue, resume, checkpoint, manifest generation
- [ ] Notifications: macOS + iMessage on job completion
- [ ] Tests: adapter tests with recorded responses (VCR pattern)

End state: `econscope pull --source fred --series PSAVERT` works, stores data, logs audit trail.

### Phase 2: Catalog + browse interface (week 3)

**Goal:** Know what's available across all sources before pulling.

Deliverables:
- [ ] Catalog builder: script that harvests series metadata from each source
- [ ] Catalog schema: source, series_id, description, geography, frequency, tags
- [ ] GitHub Pages site: search bar, source browser, tag filters, series detail view
- [ ] Catalog CI: GitHub Action rebuilds catalog weekly
- [ ] CLI: `econscope catalog search "inflation UK"` (local search over cached catalog)

End state: `ihelfrich.github.io/econscope` is a searchable catalog of 1M+ data series.

### Phase 3: More adapters + research targets (week 4-5)

**Goal:** Cover all major sources. Batch acquisition works.

Deliverables:
- [ ] Adapters: Census, EIA, FHFA, FDIC, CFTC, CFPB, Finnhub, FMP, Polygon
- [ ] Adapters: UK ONS, Bank of England, Companies House, ECB, Eurostat
- [ ] Adapters: IMF, World Bank, OECD, ILO, UN Comtrade, SIPRI
- [ ] Adapters: OpenAlex, Semantic Scholar (academic)
- [ ] Research target system: YAML spec, scoping query, plan generation, execution
- [ ] Multi-target plans: parallel execution across sources
- [ ] Progress notifications at configurable intervals

End state: `econscope target create "full macro context" --plan us_macro_2024.yaml` runs overnight, pulls everything, notifies when done.

### Phase 4: Parse, extract, knowledge graph (week 6-8)

**Goal:** Raw data becomes structured intelligence.

Deliverables:
- [ ] Document parser pipeline: PDF, DOCX, HTML → structured text
- [ ] Entity extractor: spaCy NER + nomenklatura resolution
- [ ] Financial extractor: XBRL → standardized financial statements
- [ ] Knowledge graph schema: nodes, edges, temporal attributes
- [ ] Graph operations: shortest path, common neighbors, centrality, community detection
- [ ] Integration: every adapter's output feeds the graph automatically
- [ ] Wire in existing tools: forensic-econ, deepwire, groundtruth as graph feeders

End state: run a company analysis, then query `econscope graph path "Ron Burkle" "Apollo Global"` and get the connection chain.

### Phase 5: Analysis engines (week 9-12)

**Goal:** Automated analytical intelligence, not just data retrieval.

Deliverables:
- [ ] Financial forensics engine: Beneish, Altman, Sloan, Piotroski, DuPont, FCF quality (extend forensic-econ)
- [ ] Network analysis engine: wrap deepwire + add influence scoring, contagion modeling
- [ ] Geospatial engine: spatial autocorrelation, OT distance metrics, property footprint mapping
- [ ] Macro analysis engine: trend decomposition, structural breaks, VAR, distributional analysis
- [ ] Sector benchmarking: percentile ranking within SIC/NAICS peer group
- [ ] Legal/regulatory scoring: enforcement frequency, litigation intensity, patent portfolio strength
- [ ] Anomaly detection: Benford's law, statistical outliers, sudden relationship changes
- [ ] Audit engine: local, global, super-global consistency checks

End state: `econscope analyze company "Soho House" --full` produces a structured analysis object covering all dimensions.

### Phase 6: Report generation (week 13-15)

**Goal:** Analysis becomes publication-quality output.

Deliverables:
- [ ] LaTeX template system: master template with brand identity (palette, typography, grid)
- [ ] Quarto template: HTML version with interactive charts
- [ ] Chart generator: matplotlib + D3 templates using brand palette
- [ ] Auto-report builder: analysis object → complete report with narrative, charts, citations
- [ ] Citation manager: auto-generate APA/Chicago from audit trail
- [ ] Export pipeline: PDF, HTML, DOCX, PPTX, JSON
- [ ] Teaching layer system: tcolorbox annotations (gold/wine/rust/sage pattern from Shane reports)

End state: `econscope report company "Soho House" --format pdf --template deep_dive` produces a 40+ page report.

### Phase 7: Visual identity + brand (parallel track, week 1-4)

**Goal:** Reports look like they come from a serious institution.

This runs in parallel with the technical build:

- [ ] Research phase: teardown 10 exemplar report designs (Bridgewater, BIS, Citadel, Economist, Chainalysis, etc.)
- [ ] Color system: build from Carolina Blue + GT Gold + Ukraine influence, test for accessibility
- [ ] Typography: select serif (body) + sans-serif (headings/data) + monospace (code/data tables)
- [ ] Grid system: page layout, margin ratios, information density targets
- [ ] Chart style guide: axis treatment, annotation style, color usage rules
- [ ] Cover page architecture: 3-4 cover variants for different report types
- [ ] Icon/mark system: logomark for the brand (even before naming)
- [ ] Apply to LaTeX + Quarto templates
- [ ] Apply to GitHub Pages catalog
- [ ] Apply to Electron hub UI

### Phase 8: Electron hub + unified interface (week 16-18)

**Goal:** Everything accessible from one local application.

Deliverables:
- [ ] Electron app: absorbs company-dissector, adds all new capabilities
- [ ] Tabs: Search/Catalog, Company, Sector, Person, Macro, Network, Reports, Jobs, Settings
- [ ] Real-time job monitoring from the GUI
- [ ] Interactive graph visualization (Cytoscape.js or D3 force)
- [ ] Report preview and export from the GUI
- [ ] Keyboard-driven workflow (power-user optimized)

### Phase 9: Institutional crawl layer (week 19-22)

**Goal:** Systematically harvest and parse institutional research.

Deliverables:
- [ ] Domain profiles for each institutional source (URL patterns, crawl rules, parse templates)
- [ ] Scheduled crawls: web-intel runs nightly/weekly against configured domains
- [ ] PDF extraction pipeline: GROBID for academic, custom for consultancy reports
- [ ] Structured extraction: key findings, data tables, entity mentions
- [ ] Index into document store + knowledge graph
- [ ] Sector-specific source registry: which sources matter for which sectors

### Phase 10: GodsEye integration + physical-world intelligence (week 23+)

**Goal:** Connect the economic intelligence layer to physical-world data.

Deliverables:
- [ ] AIS integration: track shipping patterns for supply chain analysis
- [ ] ADS-B integration: corporate aviation tracking (who's flying where)
- [ ] Satellite imagery: nightlights as economic activity proxy
- [ ] IoT/sensor data: environmental monitoring for ESG analysis
- [ ] Physical-digital correlation: match shipping data to trade flows, flight data to M&A activity

---

## Comparison: what this is vs. what exists

| Capability | Bloomberg Terminal | Palantir Foundry | D.E. Shaw | This platform |
|---|---|---|---|---|
| Real-time market data | Best in class | No | Proprietary | Good (free tier APIs) |
| Financial forensics | Basic screens | Custom per client | Proprietary | Deep (6+ models, automated) |
| Corporate network mapping | Limited | Strong | Unknown | Very strong (deepwire + graph) |
| Geospatial intelligence | No | Strong | No | Strong (GodsEye + groundtruth + OT) |
| Economic modeling | No | No | Proprietary | Strong (Topology Engine + academic econ) |
| Legal/regulatory intelligence | Basic | Custom | No | Strong (CourtListener + PACER + patents) |
| Property intelligence | No | No | No | Unique (groundtruth) |
| Institutional report synthesis | Yes (paid research) | No | Proprietary | Automated crawl + parse |
| Physical-world monitoring | No | Yes (mil/intel) | No | Emerging (GodsEye) |
| Persistent knowledge graph | No | Yes | Unknown | Yes (accumulates with each analysis) |
| Reproducible audit trail | No | Partial | Unknown | Full (every number traced to source) |
| Open source / self-hosted | No ($25K/yr) | No ($millions) | No (hedge fund) | Yes (you own everything) |
| Economist's structural lens | No | No | Partially | **Unique edge** |

The genuine differentiator is the last row. Bloomberg gives you data. Palantir gives you a platform. Shaw gives you alpha.
This gives you an economist's understanding of how the data connects — trade networks, spatial heterogeneity,
optimal transport, distributional analysis — applied through a fully instrumented, self-auditing pipeline
that gets smarter with every analysis it runs.

---

## File structure

```
~/Projects/econscope/
├── pyproject.toml              # Package definition (uv/pip)
├── Makefile                    # Build, test, deploy commands
├── .env.example                # Template for API keys
├── ARCHITECTURE.md             # This document
├── README.md                   # Public-facing project description
│
├── econscope/                  # Main Python package
│   ├── __init__.py
│   ├── cli.py                  # typer CLI entry point
│   │
│   ├── adapters/               # One file per data source
│   │   ├── base.py             # Abstract adapter interface
│   │   ├── fred.py
│   │   ├── bls.py
│   │   ├── bea.py
│   │   ├── census.py
│   │   ├── treasury.py
│   │   ├── eia.py
│   │   ├── edgar.py            # Wraps forensic-econ Go binary
│   │   ├── dbnomics.py
│   │   ├── imf.py
│   │   ├── worldbank.py
│   │   ├── oecd.py
│   │   ├── eurostat.py
│   │   ├── ecb.py
│   │   ├── boe.py              # Bank of England
│   │   ├── ons.py              # UK ONS
│   │   ├── companies_house.py
│   │   ├── finnhub.py
│   │   ├── fmp.py
│   │   ├── polygon.py
│   │   ├── openalex.py
│   │   ├── semantic_scholar.py
│   │   ├── courtlistener.py
│   │   ├── opensanctions.py
│   │   ├── opencorporates.py
│   │   ├── wikidata.py
│   │   ├── gdelt.py
│   │   ├── littlesis.py
│   │   ├── uspto.py
│   │   ├── cfpb.py
│   │   ├── fdic.py
│   │   ├── fhfa.py
│   │   ├── cftc.py
│   │   └── web_intel.py        # Wraps web-intel Go binary
│   │
│   ├── engine/                 # Rate governing + job system
│   │   ├── governor.py         # Token-bucket rate limiter
│   │   ├── scheduler.py        # Job queue + execution
│   │   ├── targets.py          # Research target specs
│   │   ├── plans.py            # Multi-target plan orchestration
│   │   └── notify.py           # macOS, iMessage, Pushover
│   │
│   ├── extract/                # Layer 2: parse + extract
│   │   ├── documents.py        # PDF, DOCX, HTML parsing
│   │   ├── entities.py         # NER + entity resolution
│   │   ├── financials.py       # XBRL + table extraction
│   │   ├── geospatial.py       # Address resolution, geocoding
│   │   └── citations.py        # Auto-generate APA/Chicago
│   │
│   ├── store/                  # Layer 3: storage
│   │   ├── warehouse.py        # DuckDB interface
│   │   ├── graph.py            # Knowledge graph (networkx + SQLite)
│   │   ├── documents.py        # Document store (SHA1 sharded)
│   │   └── search.py           # Full-text search (FTS5)
│   │
│   ├── analyze/                # Layer 4: analysis engines
│   │   ├── forensics.py        # Financial scoring models
│   │   ├── network.py          # Network/influence analysis
│   │   ├── geospatial.py       # Spatial econometrics
│   │   ├── macro.py            # Macro/sector analysis
│   │   ├── legal.py            # Legal/regulatory scoring
│   │   └── anomaly.py          # Statistical anomaly detection
│   │
│   ├── intel/                  # Layer 5: intelligence
│   │   ├── crossref.py         # Cross-reference engine
│   │   ├── accumulate.py       # Knowledge graph enrichment
│   │   ├── audit.py            # Local/global/super-global audit
│   │   └── modes.py            # COMPANY, SECTOR, PERSON, MACRO, NETWORK
│   │
│   ├── report/                 # Layer 6: output
│   │   ├── templates/          # LaTeX + Quarto templates
│   │   ├── charts.py           # matplotlib + D3 chart generators
│   │   ├── builder.py          # Analysis → report assembly
│   │   └── export.py           # PDF, HTML, DOCX, PPTX
│   │
│   └── brand/                  # Visual identity
│       ├── palette.py          # Color definitions
│       ├── typography.py       # Font stack
│       └── style.py            # Chart/report style application
│
├── catalog/                    # Series catalog for GitHub Pages
│   ├── build_catalog.py        # Harvests metadata from all sources
│   ├── catalog.json            # Generated index (not committed if huge)
│   └── site/                   # Static site files
│       ├── index.html
│       ├── app.js
│       └── style.css
│
├── templates/                  # Report templates
│   ├── latex/
│   │   ├── deep_dive.tex
│   │   ├── sector_brief.tex
│   │   ├── macro_outlook.tex
│   │   └── executive_summary.tex
│   └── quarto/
│       ├── deep_dive.qmd
│       └── _quarto.yml
│
├── tests/
│   ├── adapters/               # Per-adapter tests with recorded responses
│   ├── engine/
│   ├── analyze/
│   └── fixtures/               # VCR cassettes / recorded API responses
│
├── scripts/
│   ├── register_apis.sh        # Opens all registration URLs
│   └── verify_keys.py          # Tests each API key works
│
└── electron/                   # Electron hub (Phase 8)
    ├── package.json
    ├── main.js
    └── renderer/
```

---

## What makes this "beyond D.E. Shaw"

Shaw has faster execution and better real-time data. They don't publish their methods.

This platform has four things Shaw doesn't offer the world:

1. **The economist's lens.** Optimal transport distances between markets. Network centrality of firms in the global trade graph. Spatial heterogeneity in how macro shocks propagate. Distributional analysis that disaggregates "the consumer" into income quintiles. This is your PhD, applied.

2. **The accumulating graph.** Every analysis enriches the next one. After 100 company analyses, the knowledge graph contains thousands of entities and tens of thousands of relationships. Pattern recognition that would take a human analyst years happens automatically.

3. **The audit trail.** Every number in every report traces to a specific API call, with a hash, a timestamp, and an assertion. No other platform in the world does this for economic research. It makes every report reproducible and defensible.

4. **It's yours.** Self-hosted, open (or proprietary, your choice), no $25K Bloomberg terminal, no $2M Palantir contract, no hedge fund secrecy. An independent economist with better tooling than most institutions.

---

*This document is the development blueprint. Update it as decisions are made and phases are completed.*

