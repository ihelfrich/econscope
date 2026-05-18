# ECONSCOPE

A unified economic intelligence platform that pulls, stores, audits, and analyzes data from 50+ government, financial, legal, and academic sources through a single CLI.

Every number traces to a named source. Every pull is logged with a hash and timestamp. The warehouse accumulates across sessions.

## Quick start

```bash
# Clone and install
git clone https://github.com/ihelfrich/econscope.git
cd econscope
pip install -e .

# Add your API keys
cp .env.example .env
# Edit .env with your keys (see below for registration links)

# Search, pull, query
econscope search fred "personal savings rate"
econscope pull fred PSAVERT --start 2019-01-01
econscope query fred PSAVERT --start 2024-01-01 --format csv
econscope audit
```

## What it does

```
econscope search <source> <query>          # find series across sources
econscope pull <source> <series_id>        # pull + store + audit trail
econscope query <source> <series_id>       # query stored data (table/csv/json)
econscope info <source> <series_id>        # show series metadata
econscope audit                            # view provenance log
econscope verify-keys                      # test all API keys
```

## Data sources

### Active adapters

| Source | Coverage | Key required |
|--------|----------|:------------:|
| **FRED** | 800K+ macro time series (rates, GDP, employment, housing, money supply) | Yes (free) |
| **BLS** | CPI, employment, wages, JOLTS, productivity, consumer expenditure | Yes (free) |

### Wired (key in .env, adapter coming)

| Source | Coverage |
|--------|----------|
| BEA | GDP, PCE, personal income, IO tables |
| Census | ACS demographics, County Business Patterns, trade |
| EIA | Oil, gas, coal, electricity, renewables |
| Finnhub | Real-time quotes, insider transactions, ESG scores |
| CourtListener | US court opinions, PACER dockets |
| Financial Modeling Prep | Financial statements, ratios, DCF |
| Alpha Vantage | Historical prices, forex, economic indicators |
| UK Companies House | Company filings, officers, PSCs |

### No key needed (adapter coming)

SEC EDGAR, DBnomics (70+ providers), IMF, World Bank, OECD, Eurostat, ECB, Bank of England, UK ONS, Treasury FiscalData, FHFA, FDIC, CFPB, CFTC, USPTO, OpenAlex, Semantic Scholar, Wikidata, GDELT, LittleSis, SIPRI, ILO, Penn World Table, Maddison Project.

## Storage

All data goes into a local [DuckDB](https://duckdb.org) warehouse at `data/warehouse.duckdb`. Every pull logs:

- Source and series ID
- Request parameters
- Timestamp
- Record count
- SHA-256 hash of the raw API response
- Pass/fail assertions

Query the audit trail directly:

```sql
duckdb data/warehouse.duckdb "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 10"
```

## API key registration

Run `bash scripts/register_apis.sh p0` to open the three most important registration pages. All keys are free.

| Priority | Source | Register |
|:--------:|--------|----------|
| P0 | FRED | [research.stlouisfed.org](https://research.stlouisfed.org/useraccount/apikeys) |
| P0 | BLS | [data.bls.gov](https://data.bls.gov/registrationEngine/) |
| P0 | BEA | [apps.bea.gov](https://apps.bea.gov/API/signup/) |
| P1 | Census | [census.gov](https://api.census.gov/data/key_signup.html) |
| P1 | EIA | [eia.gov](https://www.eia.gov/opendata/register.php) |
| P1 | UK Companies House | [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk/) |
| P2 | Finnhub | [finnhub.io](https://finnhub.io/register) |
| P2 | FMP | [financialmodelingprep.com](https://site.financialmodelingprep.com/developer/docs) |
| P2 | Alpha Vantage | [alphavantage.co](https://www.alphavantage.co/support/#api-key) |
| P2 | CourtListener | [courtlistener.com](https://www.courtlistener.com/register/) |

See `.env.example` for the full list with env var names.

## Adding a new source

1. Add the source to `sources.yaml`
2. Create `econscope/adapters/<source_id>.py` implementing `BaseAdapter`
3. Register it in `econscope/cli.py` → `_get_adapter()`
4. Add any API key to `.env.example` and `.env`
5. Test: `econscope search <source_id> "test query"`

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design, including the knowledge graph schema, rate-governed batch acquisition system, analysis engine specs, and build phases.

## Existing tools integrated

This platform unifies several standalone tools:

| Tool | Role |
|------|------|
| [web-intel](https://github.com/ihelfrich) | Parallel Go web crawler (2,300 URL/s) |
| [forensic-econ](https://github.com/ihelfrich) | SEC EDGAR/XBRL + financial forensics |
| [deepwire](https://github.com/ihelfrich) | Network/connection discovery engine |
| [company-dissector](https://github.com/ihelfrich) | 12-tab corporate profiling GUI |
| [groundtruth](https://github.com/ihelfrich) | Property intelligence (NYC + UK) |

## License

TBD

## Author

**Dr. Ian Helfrich** — PhD Economics, Georgia Institute of Technology
[ianhelfrich.com](https://ianhelfrich.com) · [GitHub](https://github.com/ihelfrich)
