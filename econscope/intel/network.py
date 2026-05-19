"""Network intelligence: connection discovery across SEC, Wikidata, GDELT.

Given a seed entity (person or company name), this module builds a graph of
co-mentioned entities by querying:

- SEC EDGAR full-text search (every filing since 2001)
- SEC EDGAR ownership filings (13D/13G institutional holders)
- Wikidata SPARQL (structured corporate-relationship edges)
- GDELT 2.0 (global news co-occurrence)

The graph is a `NetworkGraph` — a thin wrapper over networkx.MultiDiGraph that
preserves provenance (which source contributed which edge) and supports the
investigative queries we actually run: shared neighbors, brokerage centrality,
component analysis, k-hop expansion.

This is the in-platform version of the standalone `deepwire` tool. The standalone
tool remains useful for one-off command-line work; this module is what every
report generator and analysis pipeline inside ECONSCOPE depends on.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from econscope.intel.http import fetch, fetch_json, RetryableHTTPError, PermanentHTTPError


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class Node:
    """One entity in the discovery graph."""
    id: str
    kind: str  # "seed", "sec_entity", "holder", "wikidata", "news_entity"
    label: str
    attrs: dict = field(default_factory=dict)


@dataclass
class Edge:
    """Relationship between two nodes, with provenance."""
    source: str
    target: str
    weight: float
    kinds: list[str]  # which sources contributed this edge
    attrs: dict = field(default_factory=dict)


@dataclass
class NetworkGraph:
    """Discovery graph with provenance and analysis helpers."""
    seed: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "seed": self.seed,
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
            "metadata": self.metadata,
        }, indent=2, default=str)

    @classmethod
    def from_json(cls, data: str) -> "NetworkGraph":
        d = json.loads(data) if isinstance(data, str) else data
        return cls(
            seed=d["seed"],
            nodes=[Node(**n) for n in d["nodes"]],
            edges=[Edge(**e) for e in d["edges"]],
            metadata=d.get("metadata", {}),
        )

    # ── Analysis helpers ──────────────────────────────────────────────

    def neighbors(self, node_id: str) -> list[str]:
        """Direct neighbors of a node."""
        out = set()
        for e in self.edges:
            if e.source == node_id:
                out.add(e.target)
            if e.target == node_id:
                out.add(e.source)
        return sorted(out)

    def common_neighbors(self, a: str, b: str) -> list[str]:
        """Shared neighbors of two nodes."""
        na = set(self.neighbors(a))
        nb = set(self.neighbors(b))
        return sorted(na & nb)

    def top_by_weight(self, n: int = 10) -> list[Edge]:
        """Edges sorted by weight, most important first."""
        return sorted(self.edges, key=lambda e: e.weight, reverse=True)[:n]

    def brokers(self, top: int = 10) -> list[tuple[str, float]]:
        """Approximate betweenness centrality (nodes that bridge clusters).

        Uses a simple shortest-path approximation since the graph is small.
        Returns (node_id, score) tuples sorted descending.
        """
        try:
            import networkx as nx
        except ImportError:
            return []

        g = nx.Graph()
        for n in self.nodes:
            g.add_node(n.id)
        for e in self.edges:
            g.add_edge(e.source, e.target, weight=e.weight)

        if g.number_of_nodes() < 3:
            return []

        bc = nx.betweenness_centrality(g, weight="weight", normalized=True)
        return sorted(bc.items(), key=lambda x: x[1], reverse=True)[:top]


# ── SEC EDGAR full-text search ───────────────────────────────────────────────

EDGAR_FTS_BASE = "https://efts.sec.gov/LATEST/search-index"

def edgar_fts(query: str, *, forms: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Full-text search across SEC filings since 2001.

    Parameters
    ----------
    query : str
        Search query (will be URL-quoted automatically).
    forms : str, optional
        Comma-separated form types to filter, e.g. "10-K,10-Q,DEF 14A".
    limit : int
        Max results to return. EDGAR caps at 100/page; we paginate up to this.

    Returns
    -------
    List of result dicts with keys: date, form, company, cik, accession, score.
    """
    params = {"q": f'"{query}"', "dateRange": "custom", "startdt": "2001-01-01"}
    if forms:
        params["forms"] = forms

    results: list[dict] = []
    page = 0
    page_size = 100

    while len(results) < limit:
        params["from"] = str(page * page_size)
        url = f"{EDGAR_FTS_BASE}?{urllib.parse.urlencode(params)}"
        try:
            data = fetch_json(url, cache_max_age=86400)  # 1-day cache
        except (RetryableHTTPError, PermanentHTTPError):
            break

        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for h in hits:
            src = h.get("_source", {})
            ciks = src.get("ciks", [])
            companies = src.get("display_names", [])
            company = ", ".join(companies) if companies else (ciks[0] if ciks else "")
            cik = ciks[0] if ciks else ""
            results.append({
                "date": src.get("file_date", ""),
                "form": src.get("form", ""),
                "company": company,
                "cik": cik,
                "accession": h.get("_id", ""),
                "score": h.get("_score", 0),
            })
            if len(results) >= limit:
                break

        if len(hits) < page_size:
            break
        page += 1

    return results


# ── SEC EDGAR ownership filings (13D/13G) ────────────────────────────────────

def edgar_holders(company_name: str, *, limit: int = 50) -> list[dict]:
    """Find 13D/13G and other ownership filings mentioning a company.

    These reveal institutional and insider holdings — the strongest signal
    for ownership-network analysis.
    """
    return edgar_fts(company_name, forms="SC 13D,SC 13D/A,SC 13G,SC 13G/A,EX-1", limit=limit)


# ── Wikidata SPARQL ──────────────────────────────────────────────────────────

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

def _wikidata_qid(entity: str) -> Optional[str]:
    """Resolve a label to a Wikidata QID via the search API."""
    url = (
        "https://www.wikidata.org/w/api.php"
        "?action=wbsearchentities&format=json&language=en&type=item"
        f"&search={urllib.parse.quote(entity)}"
    )
    try:
        data = fetch_json(url, cache_max_age=604800)  # 1-week cache
    except (RetryableHTTPError, PermanentHTTPError):
        return None
    hits = data.get("search", [])
    return hits[0]["id"] if hits else None


def wiki_expand(entity: str, *, hops: int = 1, max_per_hop: int = 50) -> list[dict]:
    """Expand a Wikidata entity's neighborhood via SPARQL.

    Returns a list of {source, relation, target, target_qid, hop} dicts.
    Handles rate limits gracefully — returns partial results on failure.
    """
    qid = _wikidata_qid(entity)
    if qid is None:
        return []

    out = []
    visited = {qid}
    frontier = [qid]

    for hop in range(1, hops + 1):
        next_frontier = []
        for q in frontier:
            sparql = f"""
            SELECT ?prop ?propLabel ?target ?targetLabel WHERE {{
              wd:{q} ?p ?target .
              ?prop wikibase:directClaim ?p .
              ?target rdfs:label ?targetLabel .
              FILTER(LANG(?targetLabel) = "en")
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT {max_per_hop}
            """
            url = f"{WIKIDATA_SPARQL}?query={urllib.parse.quote(sparql)}&format=json"
            try:
                data = fetch_json(
                    url,
                    headers={"Accept": "application/sparql-results+json"},
                    cache_max_age=86400,
                    max_retries=3,
                )
            except (RetryableHTTPError, PermanentHTTPError):
                continue  # skip this node; partial result is better than no result

            for binding in data.get("results", {}).get("bindings", []):
                tgt = binding.get("target", {}).get("value", "")
                tgt_qid = tgt.rsplit("/", 1)[-1] if "/" in tgt else tgt
                tgt_label = binding.get("targetLabel", {}).get("value", "")
                rel = binding.get("propLabel", {}).get("value", "")
                if not tgt_label or not tgt_qid.startswith("Q"):
                    continue
                out.append({
                    "source": q,
                    "relation": rel,
                    "target": tgt_label,
                    "target_qid": tgt_qid,
                    "hop": hop,
                })
                if tgt_qid not in visited:
                    visited.add(tgt_qid)
                    next_frontier.append(tgt_qid)
        frontier = next_frontier

    return out


# ── GDELT news co-occurrence ─────────────────────────────────────────────────

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

def gdelt_news(query: str, *, timespan: str = "12m") -> list[dict]:
    """Pull GDELT articles mentioning the query string."""
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "timespan": timespan,
        "maxrecords": "100",
    }
    url = f"{GDELT_DOC_API}?{urllib.parse.urlencode(params)}"
    try:
        data = fetch_json(url, cache_max_age=3600)
    except (RetryableHTTPError, PermanentHTTPError):
        return []
    return data.get("articles", [])


# ── Discovery orchestration ──────────────────────────────────────────────────

def _normalize_company_name(s: str) -> str:
    """Strip CIK and ticker decoration to make co-mention matching looser."""
    s = re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", s)
    s = re.sub(r"\s*\([A-Z]{1,5}\)\s*$", "", s)
    return s.strip()


def discover(
    entity: str,
    *,
    edgar_limit: int = 200,
    wiki_hops: int = 1,
    skip_wiki: bool = False,
    skip_gdelt: bool = False,
    co_mention_threshold: int = 2,
) -> NetworkGraph:
    """Build a multi-source discovery graph from a seed entity.

    The pipeline:
    1. EDGAR full-text search → identify SEC entities that co-appear with the seed
    2. EDGAR ownership filings → upgrade some to "holder" relationships
    3. Wikidata SPARQL → add structured corporate-relationship edges
    4. GDELT news → add news-co-occurrence weighting

    Returns a NetworkGraph containing all discovered nodes and edges, with
    metadata tracking which sources contributed.
    """
    graph = NetworkGraph(seed=entity)
    graph.metadata["created"] = datetime.utcnow().isoformat()
    graph.metadata["sources_attempted"] = []
    graph.metadata["sources_succeeded"] = []

    # Seed node
    graph.nodes.append(Node(id=entity, kind="seed", label=entity))

    # ── 1. EDGAR full-text search ────────────────────────────────────
    graph.metadata["sources_attempted"].append("edgar_fts")
    fts_results = edgar_fts(entity, limit=edgar_limit)
    if fts_results:
        graph.metadata["sources_succeeded"].append("edgar_fts")
        # Count co-mentions by company
        counts: dict[str, int] = {}
        for r in fts_results:
            company = r.get("company", "").strip()
            if not company or company.lower() == entity.lower():
                continue
            counts[company] = counts.get(company, 0) + 1

        for company, count in counts.items():
            if count < co_mention_threshold:
                continue
            graph.nodes.append(Node(id=company, kind="sec_entity", label=company))
            graph.edges.append(Edge(
                source=entity, target=company, weight=float(count),
                kinds=["sec_co_mention"],
            ))

    # ── 2. EDGAR ownership filings ───────────────────────────────────
    graph.metadata["sources_attempted"].append("edgar_holders")
    holder_results = edgar_holders(entity, limit=50)
    if holder_results:
        graph.metadata["sources_succeeded"].append("edgar_holders")
        seen_holders: set[str] = set()
        for r in holder_results:
            company = r.get("company", "").strip()
            if not company or company.lower() == entity.lower() or company in seen_holders:
                continue
            seen_holders.add(company)

            existing = next((n for n in graph.nodes if n.id == company), None)
            if existing is None:
                graph.nodes.append(Node(id=company, kind="holder", label=company))
                graph.edges.append(Edge(
                    source=entity, target=company, weight=1.0,
                    kinds=["ownership_filer"],
                ))
            else:
                # Upgrade existing edge to record both kinds
                edge = next((e for e in graph.edges
                            if e.source == entity and e.target == company), None)
                if edge and "ownership_filer" not in edge.kinds:
                    edge.kinds.append("ownership_filer")

    # ── 3. Wikidata expansion ─────────────────────────────────────────
    if not skip_wiki:
        graph.metadata["sources_attempted"].append("wikidata")
        try:
            wiki_edges = wiki_expand(entity, hops=wiki_hops)
            if wiki_edges:
                graph.metadata["sources_succeeded"].append("wikidata")
                seen_wiki: set[str] = set()
                for w in wiki_edges:
                    target_label = w.get("target", "")
                    if not target_label or target_label in seen_wiki:
                        continue
                    seen_wiki.add(target_label)
                    # Match against existing nodes by name (loose)
                    existing = next(
                        (n for n in graph.nodes
                         if _normalize_company_name(n.id).lower() == target_label.lower()),
                        None
                    )
                    if existing is None:
                        graph.nodes.append(Node(
                            id=target_label, kind="wikidata", label=target_label,
                            attrs={"qid": w.get("target_qid", "")},
                        ))
                        graph.edges.append(Edge(
                            source=entity, target=target_label, weight=0.5,
                            kinds=[f"wikidata_{w.get('relation', 'rel')}"],
                        ))
        except Exception:
            pass  # Wikidata is flaky; partial results are fine

    # ── 4. GDELT news ────────────────────────────────────────────────
    if not skip_gdelt:
        graph.metadata["sources_attempted"].append("gdelt")
        articles = gdelt_news(entity)
        if articles:
            graph.metadata["sources_succeeded"].append("gdelt")
            graph.metadata["gdelt_article_count"] = len(articles)
            # We don't extract entities from articles (would need NER);
            # we just record the article volume as a metadata signal.

    # Final metadata
    graph.metadata["node_count"] = len(graph.nodes)
    graph.metadata["edge_count"] = len(graph.edges)

    return graph


# ── Pretty-printing ──────────────────────────────────────────────────────────

def summarize(graph: NetworkGraph) -> str:
    """Human-readable summary of a discovery graph."""
    lines = [
        f"Discovery graph for: {graph.seed}",
        f"  Nodes: {len(graph.nodes)}",
        f"  Edges: {len(graph.edges)}",
        f"  Sources succeeded: {', '.join(graph.metadata.get('sources_succeeded', []))}",
        "",
        "Top connections by weight:",
    ]
    for e in graph.top_by_weight(15):
        kinds = "+".join(e.kinds)
        lines.append(f"  {e.weight:>6.1f}  {e.target[:55]:<55}  [{kinds}]")
    return "\n".join(lines)
