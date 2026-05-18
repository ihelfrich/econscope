#!/usr/bin/env python3
"""
Verify all ECONSCOPE API keys by making a minimal test request to each service.
Usage: python3 scripts/verify_keys.py
"""

import os
import sys
import json
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

# Load .env manually (no dependencies needed)
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if value:
                os.environ[key.strip()] = value.strip()

def test_request(url, headers=None, timeout=10):
    req = Request(url, headers=headers or {})
    try:
        resp = urlopen(req, timeout=timeout)
        return resp.status, None
    except HTTPError as e:
        return e.code, str(e)
    except (URLError, TimeoutError) as e:
        return 0, str(e)

def check(name, env_var, test_url_fn):
    key = os.environ.get(env_var, "")
    if not key:
        return "skip", f"  [ ] {name:30s} — no key set ({env_var})"

    url, headers = test_url_fn(key)
    status, err = test_request(url, headers)

    if 200 <= status < 300:
        return "pass", f"  [x] {name:30s} — OK (HTTP {status})"
    elif status == 401 or status == 403:
        return "fail", f"  [!] {name:30s} — INVALID KEY (HTTP {status})"
    elif status == 429:
        return "pass", f"  [x] {name:30s} — key accepted (rate limited, HTTP 429)"
    else:
        return "fail", f"  [!] {name:30s} — ERROR: {err or f'HTTP {status}'}"

# ── Test definitions ────────────────────────────────────────────────────────

checks = [
    ("FRED", "FRED_API_KEY",
     lambda k: (f"https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key={k}&file_type=json", {})),

    ("BLS", "BLS_API_KEY",
     lambda k: ("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                {"Content-Type": "application/json"})),

    ("BEA", "BEA_API_KEY",
     lambda k: (f"https://apps.bea.gov/api/data/?method=GetDataSetList&UserID={k}&ResultFormat=JSON", {})),

    ("Census", "CENSUS_API_KEY",
     lambda k: (f"https://api.census.gov/data/2022/acs/acs5?get=NAME&for=state:01&key={k}", {})),

    ("EIA", "EIA_API_KEY",
     lambda k: (f"https://api.eia.gov/v2/?api_key={k}", {})),

    ("Finnhub", "FINNHUB_API_KEY",
     lambda k: (f"https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token={k}", {})),

    ("Financial Modeling Prep", "FMP_API_KEY",
     lambda k: (f"https://financialmodelingprep.com/api/v3/profile/AAPL?apikey={k}", {})),

    ("Alpha Vantage", "ALPHA_VANTAGE_KEY",
     lambda k: (f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AAPL&apikey={k}", {})),

    ("Polygon.io", "POLYGON_API_KEY",
     lambda k: (f"https://api.polygon.io/v3/reference/tickers/AAPL?apiKey={k}", {})),

    ("Tiingo", "TIINGO_API_KEY",
     lambda k: ("https://api.tiingo.com/api/test", {"Authorization": f"Token {k}"})),

    ("OpenCorporates", "OPENCORPORATES_API_TOKEN",
     lambda k: (f"https://api.opencorporates.com/v0.4/companies/search?q=apple&api_token={k}", {})),

    ("OpenSanctions", "OPENSANCTIONS_API_KEY",
     lambda k: ("https://api.opensanctions.org/search/default?q=test&limit=1",
                {"Authorization": f"ApiKey {k}"})),

    ("CourtListener", "COURTLISTENER_API_TOKEN",
     lambda k: ("https://www.courtlistener.com/api/rest/v4/search/?q=test&type=o",
                {"Authorization": f"Token {k}"})),
]

# ── No-key sources (just check they're reachable) ──────────────────────────

no_key_checks = [
    ("SEC EDGAR", "https://efts.sec.gov/LATEST/search-index?q=test&dateRange=custom&startdt=2024-01-01&enddt=2024-01-02"),
    ("DBnomics", "https://db.nomics.world/api/v22/series?limit=1"),
    ("World Bank", "https://api.worldbank.org/v2/country/US/indicator/NY.GDP.MKTP.CD?format=json&per_page=1"),
    ("Treasury FiscalData", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?page[size]=1"),
    ("FHFA", "https://api.fhfa.gov/hpi/data?state=CA&frequency=quarterly&start_year=2024"),
    ("FRED (no key)", "https://fred.stlouisfed.org/"),
]

# ── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("ECONSCOPE — API Key Verification")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    print("\n  Keys requiring registration:")
    print("  " + "-" * 56)

    for name, env_var, test_fn in checks:
        status, msg = check(name, env_var, test_fn)
        print(msg)
        if status == "pass":
            passed += 1
        elif status == "fail":
            failed += 1
        else:
            skipped += 1

    print("\n  No-key sources (reachability check):")
    print("  " + "-" * 56)

    for name, url in no_key_checks:
        status, err = test_request(url)
        if 200 <= status < 300:
            print(f"  [x] {name:30s} — reachable (HTTP {status})")
            passed += 1
        else:
            print(f"  [!] {name:30s} — {err or f'HTTP {status}'}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed, {skipped} no key set")

    if skipped > 0:
        print(f"\n  To register missing keys, run:")
        print(f"    bash scripts/register_apis.sh")
        print(f"  Then paste keys into: ~/Projects/econscope/.env")

    sys.exit(1 if failed > 0 else 0)
