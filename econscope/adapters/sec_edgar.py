"""SEC EDGAR EFTS adapter — full-text search of SEC filings + company facts.

API docs: https://efts.sec.gov/LATEST/search-index?q=...
Company facts: https://data.sec.gov/api/xbrl/companyfacts/

No key required. Must include User-Agent with name and email per SEC policy.
Rate limit: 10 requests/sec.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from econscope.adapters.base import BaseAdapter, PullResult, SeriesMetadata


# Common XBRL concepts for company facts
XBRL_CONCEPTS = {
    "revenue": "us-gaap/Revenues",
    "net_income": "us-gaap/NetIncomeLoss",
    "total_assets": "us-gaap/Assets",
    "total_liabilities": "us-gaap/Liabilities",
    "stockholders_equity": "us-gaap/StockholdersEquity",
    "operating_income": "us-gaap/OperatingIncomeLoss",
    "eps_basic": "us-gaap/EarningsPerShareBasic",
    "eps_diluted": "us-gaap/EarningsPerShareDiluted",
    "cash": "us-gaap/CashAndCashEquivalentsAtCarryingValue",
    "long_term_debt": "us-gaap/LongTermDebt",
    "shares_outstanding": "dei/EntityCommonStockSharesOutstanding",
    "accounts_receivable": "us-gaap/AccountsReceivableNetCurrent",
    "inventory": "us-gaap/InventoryNet",
    "goodwill": "us-gaap/Goodwill",
    "depreciation": "us-gaap/DepreciationDepletionAndAmortization",
    "capex": "us-gaap/PaymentsToAcquirePropertyPlantAndEquipment",
    "dividends_paid": "us-gaap/PaymentsOfDividendsCommonStock",
    "research_dev": "us-gaap/ResearchAndDevelopmentExpense",
}

# CIK → ticker map for common companies (avoid lookup)
WELL_KNOWN = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "AMZN": "0001018724",
    "META": "0001326801",
    "TSLA": "0001318605",
    "NVDA": "0001045810",
    "JPM": "0000019617",
    "BAC": "0000070858",
    "WFC": "0000072971",
    "GS": "0000886982",
    "BRK-B": "0001067983",
    "JNJ": "0000200406",
    "PFE": "0000078003",
    "XOM": "0000034088",
    "CVX": "0000093410",
}

USER_AGENT = "econscope/1.0 (ianthelfrich@gmail.com)"


class SECEdgarAdapter(BaseAdapter):
    source_id = "sec"
    source_name = "SEC EDGAR"
    key_env_var = ""
    requests_per_minute = 50  # 10/sec is the hard cap, stay conservative

    def __init__(self):
        pass

    def _get(self, url: str) -> tuple[dict | list, bytes]:
        req = Request(url)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "application/json")
        raw = urlopen(req, timeout=30).read()
        return json.loads(raw), raw

    def pull_series(
        self, series_id: str, start: str = None, end: str = None
    ) -> PullResult:
        """Pull SEC filing data.

        series_id formats:
          - "facts:{CIK}:{concept}" → XBRL company facts time series
            e.g., "facts:0000320193:revenue" or "facts:AAPL:total_assets"
          - "filings:{CIK}" → recent filings list
          - "search:{query}" → full-text search of filings
        """
        parts = series_id.split(":", 2)
        query_type = parts[0]

        try:
            if query_type == "facts":
                identifier = parts[1] if len(parts) > 1 else ""
                concept = parts[2] if len(parts) > 2 else "revenue"
                cik = self._resolve_cik(identifier)
                return self._pull_facts(series_id, cik, concept, identifier, start, end)
            elif query_type == "filings":
                identifier = parts[1] if len(parts) > 1 else ""
                cik = self._resolve_cik(identifier)
                return self._pull_filings(series_id, cik, identifier, start, end)
            elif query_type == "search":
                query = ":".join(parts[1:]) if len(parts) > 1 else ""
                return self._pull_search(series_id, query, start, end)
            else:
                return PullResult(
                    source=self.source_id, series_id=series_id,
                    metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                    error=f"Unknown query: '{query_type}'. Use: facts, filings, search",
                )
        except Exception as e:
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(source=self.source_id, series_id=series_id),
                error=str(e),
            )

    def _resolve_cik(self, identifier: str) -> str:
        """Resolve ticker or CIK string to zero-padded CIK."""
        identifier = identifier.strip().upper()
        # Check well-known tickers
        if identifier in WELL_KNOWN:
            return WELL_KNOWN[identifier]
        # Already a CIK (all digits)
        if identifier.replace("0", "").isdigit() or identifier.isdigit():
            return identifier.zfill(10)
        # Try SEC company search
        try:
            url = f"https://efts.sec.gov/LATEST/search-index?q=%22{quote(identifier)}%22&dateRange=custom&startdt=2020-01-01&enddt=2025-12-31&forms=10-K"
            data, _ = self._get(url)
            hits = data.get("hits", {}).get("hits", [])
            if hits:
                cik = str(hits[0].get("_source", {}).get("entity_id", ""))
                return cik.zfill(10)
        except Exception:
            pass
        return identifier.zfill(10)

    def _pull_facts(self, series_id, cik, concept_key, identifier, start, end) -> PullResult:
        """Pull XBRL company facts for a specific concept."""
        # Resolve concept alias
        concept_path = XBRL_CONCEPTS.get(concept_key, concept_key)

        # Company facts API
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data, raw = self._get(url)

        company_name = data.get("entityName", identifier)

        # Navigate to the concept
        parts = concept_path.split("/")
        taxonomy = parts[0] if len(parts) > 1 else "us-gaap"
        concept_name = parts[1] if len(parts) > 1 else parts[0]

        facts = data.get("facts", {})
        taxonomy_facts = facts.get(taxonomy, {})
        concept_data = taxonomy_facts.get(concept_name, {})

        if not concept_data:
            # List available concepts
            available = list(taxonomy_facts.keys())[:10]
            return PullResult(
                source=self.source_id, series_id=series_id,
                metadata=SeriesMetadata(
                    source=self.source_id, series_id=series_id,
                    title=company_name,
                ),
                error=f"Concept '{concept_name}' not found in {taxonomy}. "
                      f"Available: {', '.join(available)}...",
            )

        label = concept_data.get("label", concept_name)
        description = concept_data.get("description", "")

        # Get units — usually USD or shares
        units_data = concept_data.get("units", {})
        observations = []
        unit_label = ""
        for unit_key, unit_values in units_data.items():
            unit_label = unit_key
            for entry in unit_values:
                # Prefer 10-K/10-Q annual/quarterly filings
                form = entry.get("form", "")
                end_date = entry.get("end", "")
                val = entry.get("val")
                if val is None or not end_date:
                    continue
                if start and end_date < start:
                    continue
                if end and end_date > end:
                    continue

                observations.append({
                    "date": end_date,
                    "value": float(val),
                    "form": form,
                    "filed": entry.get("filed", ""),
                    "fiscal_year": entry.get("fy", ""),
                    "fiscal_period": entry.get("fp", ""),
                })

        # Deduplicate: keep the latest filing per end-date+form
        seen = {}
        for obs in observations:
            key = (obs["date"], obs.get("form", ""))
            if key not in seen or obs.get("filed", "") > seen[key].get("filed", ""):
                seen[key] = obs
        observations = sorted(seen.values(), key=lambda x: x["date"])

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{company_name}: {label}",
            units=unit_label, notes=description[:200] if description else "",
        )
        if observations:
            meta.observation_start = observations[0]["date"]
            meta.observation_end = observations[-1]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_filings(self, series_id, cik, identifier, start, end) -> PullResult:
        """Pull recent filings for a company."""
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data, raw = self._get(url)

        company_name = data.get("name", identifier)
        recent = data.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        names = recent.get("primaryDocument", [])

        observations = []
        for i in range(len(forms)):
            date = dates[i] if i < len(dates) else ""
            if start and date < start:
                continue
            if end and date > end:
                continue
            observations.append({
                "date": date,
                "value": i,
                "form": forms[i] if i < len(forms) else "",
                "accession": accessions[i] if i < len(accessions) else "",
                "document": names[i] if i < len(names) else "",
            })

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"{company_name}: Recent Filings",
            notes=f"CIK: {cik}",
        )
        if observations:
            meta.observation_start = observations[-1]["date"]
            meta.observation_end = observations[0]["date"]

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def _pull_search(self, series_id, query, start, end) -> PullResult:
        """Full-text search across SEC filings."""
        params = {
            "q": query,
            "dateRange": "custom",
            "startdt": start or "2020-01-01",
            "enddt": end or "2025-12-31",
        }
        url = f"https://efts.sec.gov/LATEST/search-index?{urlencode(params)}"
        data, raw = self._get(url)

        hits = data.get("hits", {}).get("hits", [])
        total = data.get("hits", {}).get("total", {})
        total_count = total.get("value", 0) if isinstance(total, dict) else total

        observations = []
        for hit in hits[:100]:
            src = hit.get("_source", {})
            observations.append({
                "date": src.get("file_date", ""),
                "value": hit.get("_score", 0),
                "entity": src.get("display_names", [""])[0] if src.get("display_names") else "",
                "form": src.get("form_type", ""),
                "description": (src.get("display_name_matchs", [""])[0] if src.get("display_name_matchs") else "")[:200],
            })

        meta = SeriesMetadata(
            source=self.source_id, series_id=series_id,
            title=f"EDGAR Search: '{query}'",
            notes=f"{total_count} total results",
        )

        return PullResult(
            source=self.source_id, series_id=series_id,
            metadata=meta, observations=observations, raw_bytes=raw,
        )

    def search(self, query: str, limit: int = 20) -> list[SeriesMetadata]:
        """Search for companies or concepts."""
        query_lower = query.lower()
        results = []

        # Check well-known tickers
        for ticker, cik in WELL_KNOWN.items():
            if query_lower in ticker.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"facts:{ticker}:revenue",
                    title=f"{ticker} Revenue (XBRL)",
                    notes=f"CIK: {cik}",
                ))

        # Check XBRL concepts
        for key, path in XBRL_CONCEPTS.items():
            if query_lower in key or query_lower in path.lower():
                results.append(SeriesMetadata(
                    source=self.source_id,
                    series_id=f"facts:AAPL:{key}",
                    title=f"XBRL Concept: {key} ({path})",
                ))

        # Try SEC EDGAR full-text search
        if len(results) < limit:
            try:
                url = f"https://efts.sec.gov/LATEST/search-index?q={quote(query)}&forms=10-K,10-Q"
                data, _ = self._get(url)
                seen_entities = set()
                for hit in data.get("hits", {}).get("hits", [])[:limit]:
                    src = hit.get("_source", {})
                    entity_id = src.get("entity_id", "")
                    if entity_id in seen_entities:
                        continue
                    seen_entities.add(entity_id)
                    name = src.get("display_names", [""])[0] if src.get("display_names") else entity_id
                    results.append(SeriesMetadata(
                        source=self.source_id,
                        series_id=f"facts:{entity_id}:revenue",
                        title=f"{name}: Revenue",
                        notes=f"CIK: {entity_id}",
                    ))
            except Exception:
                pass

        return results[:limit]

    def get_metadata(self, series_id: str) -> SeriesMetadata:
        parts = series_id.split(":", 2)
        if parts[0] == "facts" and len(parts) > 1:
            return SeriesMetadata(
                source=self.source_id, series_id=series_id,
                title=f"SEC XBRL Facts: {parts[1]}",
            )
        return SeriesMetadata(source=self.source_id, series_id=series_id)

    def verify_key(self) -> tuple[bool, str]:
        try:
            # Pull Apple's company facts as a test
            url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
            data, _ = self._get(url)
            name = data.get("entityName", "?")
            n_concepts = len(data.get("facts", {}).get("us-gaap", {}))
            return True, f"SEC EDGAR: API accessible ({name}, {n_concepts} XBRL concepts)"
        except Exception as e:
            return False, f"SEC EDGAR: {e}"
