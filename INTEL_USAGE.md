# ECONSCOPE Intel/Analyze/Report — User Guide

This guide covers the v0.2 additions: the intel, analyze, and report layers built
on top of the existing data-ingestion CLI.

The mental model: existing commands (`pull`, `query`, `multi-pull`, etc.) move time
series into the warehouse. The new commands (`discover`, `forensic`, `proxy`,
`monte-carlo`, `viz`, `chain`) do **investigation**: extracting structure from
SEC filings, scoring companies for distress and earnings quality, and turning
the results into reports.

## Quick start

The fastest way to see what's new is to run the chain pipeline. This is the
canonical workflow: take an entity, discover its connections, score everything,
and produce a synthesis report.

```bash
cd ~/Projects/econscope
PYTHONPATH=. python3 -m econscope.cli chain "Ron Burkle" --out ./burkle_chain
```

Output is three files in `./burkle_chain/`:
- `graph.json` — the discovery graph (nodes + edges with provenance)
- `network.png` — radial visualization
- `synthesis.md` — markdown report combining the network + forensic findings

## The commands

### `discover` — connection discovery

```bash
econscope discover "Ron Burkle" --out burkle.json
econscope discover "Soho House" --skip-wiki --skip-gdelt
```

Queries SEC EDGAR full-text search (every filing since 2001), EDGAR 13D/13G
ownership filings, Wikidata SPARQL, and GDELT 2.0. Returns a NetworkGraph with
edge provenance preserved — you can always tell *which source* contributed a
given connection.

Flags worth knowing:
- `--skip-wiki` — Wikidata's SPARQL endpoint is intermittently rate-limited.
  Skip it for speed.
- `--skip-gdelt` — GDELT is slower than the others; skip if you only need SEC
  connections.
- `--threshold N` — Drop entities with fewer than N co-mentions. Default 2;
  raise to 5+ to keep only the strong connections.
- `--edgar-limit N` — Max EDGAR FTS results to fetch. Default 200.

### `forensic` — Beneish/Altman/Sloan from XBRL

```bash
econscope forensic 1846510                    # Soho House
econscope forensic 1846510 --pdf forensic.pdf
```

Pulls all fiscal-year XBRL facts from SEC EDGAR and computes:

- **Beneish M-score**: earnings-manipulation screening (Beneish 1999).
  Threshold: M > −1.78 means the financial profile is statistically similar to
  known manipulators. **Screening tool, not a verdict.**
- **Altman Z-score**: bankruptcy prediction (Altman 1968).
  Z < 1.81 = distress zone; 1.81 < Z < 2.99 = gray zone; Z > 2.99 = safe.
- **Sloan accruals ratio**: earnings quality (Sloan 1996).
  High accruals relative to cash flow indicate earnings reversion risk.

Output is a year-by-year table with flag annotations. `--pdf` renders the
report as a styled PDF via xelatex.

### `proxy` — DEFM14A / DEF 14A parser

```bash
# Soho House merger proxy (December 2025)
econscope proxy 1846510 0001140361-25-045199 --out proxy.json
```

Parses a proxy statement and extracts:
- **Summary**: first substantive paragraphs of the merger description
- **Special committee**: members, formation date, financial/legal advisors, meetings
- **Related-party transactions**: counterparties, dollar amounts, descriptions
- **Fairness opinion advisors**: named investment banks issuing opinions
- **Voting proposals**: numbered list

This is the highest-leverage new capability. Proxy filings are the
single best source for governance facts that don't appear in 10-Ks. The Soho
House proxy revealed that GHWHI, LLC (a Yucaipa affiliate) leases the Little
House West Hollywood building to Soho House — a related-party real-estate
transaction that doesn't appear anywhere else in EDGAR.

### `monte-carlo` — refinancing distress simulation

```bash
econscope monte-carlo \
    --debt 736000000 --base-oi 90000000 \
    --rate-low 0.06 --rate-high 0.11 \
    --oi-std 30000000 \
    --png mc.png
```

Runs N draws (default 10,000) of (refinancing_rate, operating_income) and
computes the interest coverage ratio under each scenario. Reports the
probability that coverage falls below the distress threshold (default 1.0x).

Outputs include the full distribution and percentile bounds. Use the
`--png` flag to render a histogram with the distress region shaded.

### `viz` — render a NetworkGraph as PNG

```bash
econscope viz burkle.json --out burkle.png
econscope viz burkle.json --layout force --max-nodes 25
```

Takes a JSON file produced by `discover` and renders it as a PNG.

- `--layout radial` (default): seed at center, others on a circle
- `--layout force`: spring layout (more organic for larger graphs)
- `--max-nodes N`: cap to top-N most-connected nodes to keep the chart readable

### `chain` — discover then forensic in one pipeline

```bash
econscope chain "Ron Burkle" --out burkle_chain --threshold 3
```

The canonical multi-step workflow:
1. Discover the entity's network
2. Render the visualization
3. Run forensic scoring on every CIK found in the graph
4. Write a synthesis markdown report combining everything

Use this when you want a one-command investigation that does the right thing.
Use the individual commands when you want to inspect intermediate results.

### `cache size | clear`

```bash
econscope cache size      # Show cache stats
econscope cache clear     # Delete all cached responses
```

The intel HTTP layer caches all idempotent GETs in `~/.cache/econscope/http/`.
This makes repeated runs of `discover` and `forensic` essentially free. Clear
the cache if you need fresh data (e.g., for a same-day re-run after a filing
update).

## Python API

Every CLI command has an equivalent Python entry point. Examples:

```python
from econscope.intel.network import discover, summarize
graph = discover("Ron Burkle", skip_gdelt=True)
print(summarize(graph))

from econscope.intel.forensic import forensic_report, summarize_report
report = forensic_report(1846510)
print(summarize_report(report))

from econscope.intel.proxies import parse_proxy
extraction = parse_proxy(1846510, "0001140361-25-045199")
for rpt in extraction.related_party_transactions:
    print(rpt.counterparty, rpt.amount)

from econscope.analyze import refinancing_simulation
r = refinancing_simulation(
    debt_amount=736e6, base_operating_income=90e6,
    rate_range=(0.06, 0.11), oi_std=30e6,
)
print(f"Distress probability: {r.distress_probability:.1%}")

from econscope.report.network_viz import render_network
render_network(graph, output="burkle.png", layout="radial")
```

## Architectural notes

### Why the HTTP layer

The standalone `deepwire` tool used `urllib.request` directly. When Wikidata
briefly returned 429 (rate-limit) during the Soho House Burkle pull, the
expansion failed silently and we lost the Wikidata layer. The new
`econscope/intel/http.py` layer fixes this:

- Exponential backoff with jitter (so retries don't dogpile)
- Honors `Retry-After` headers
- Distinguishes retryable (5xx, 429, network) from permanent (404, 403) errors
- Optional gzip file-cache keyed by URL + headers
- Single consistent User-Agent (so SEC doesn't ban us)

Every intel module uses this layer. No more silent failures.

### The intel module vs. the standalone tools

The deepwire, forensic-econ, and groundtruth standalone tools still exist and
still work. The intel module is **not** a replacement — it's the in-platform
equivalent that other ECONSCOPE modules can import without subprocess overhead.

Use the standalone tools for ad-hoc CLI work outside ECONSCOPE. Use the intel
module when you're writing analyses that combine ingestion + intel + reporting
in one Python script.

### Identification warnings in `analyze.elasticity`

We made an error in an earlier Soho House draft: computed %dQ / %dP across
years where new houses were also opening, called it an elasticity. It isn't.
When supply is changing simultaneously, the ratio is contaminated.

`analyze.elasticity.pricing_power_ratio` accepts explicit identifying
assumptions via flags (`supply_changed`, `external_shock`, `selection_concern`)
and attaches structured warnings. The caller can check `result.is_elasticity`
to know whether to interpret the number as a true demand elasticity.

This is a small thing that protects against a real economic mistake.

## Tests

```bash
cd ~/Projects/econscope
PYTHONPATH=. python3 -m pytest tests/test_intel_smoke.py -v
```

17 smoke tests covering the public API of every module. No network calls;
these run in under 5 seconds. For live-API integration tests, see
`tests/test_intel_integration.py` (TBD).
