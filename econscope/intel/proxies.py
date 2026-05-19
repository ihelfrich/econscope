"""Proxy statement intelligence: DEFM14A, DEF 14A, PRER14A parsing.

Proxy statements are the most under-utilized governance document on EDGAR. They
contain, in plain English (usually buried 100 pages in):

- The full description of any merger transaction (DEFM14A)
- The special-committee composition and process narrative
- Director and executive compensation, by individual
- Related-party transactions with full counterparty disclosure
- Voting results from prior meetings
- The fairness opinion letters from financial advisors (with assumptions)

This module pulls a proxy filing from EDGAR and extracts the sections that
matter most for governance investigation. It's deliberately rule-based (not
LLM-driven) so the extraction is reproducible and auditable — if a downstream
report cites "the special committee was formed on X date," anyone can verify
that against the source extraction.

The key insight: proxy filings are HTML, often with consistent section headers.
We anchor on those headers to find the relevant prose, then do light cleanup.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from econscope.intel.http import fetch


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class RelatedPartyTransaction:
    counterparty: str
    description: str
    amount: Optional[str] = None
    year: Optional[int] = None


@dataclass
class SpecialCommitteeFact:
    field_name: str
    value: str


@dataclass
class ProxyExtraction:
    """Structured extraction of a single proxy statement."""
    cik: int
    accession: str
    form_type: str
    filing_date: Optional[str] = None
    company: Optional[str] = None
    summary_paragraphs: list[str] = field(default_factory=list)
    special_committee: list[SpecialCommitteeFact] = field(default_factory=list)
    related_party_transactions: list[RelatedPartyTransaction] = field(default_factory=list)
    director_compensation: dict = field(default_factory=dict)
    fairness_opinion_advisors: list[str] = field(default_factory=list)
    voting_proposals: list[dict] = field(default_factory=list)
    raw_text_length: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


# ── Section anchors ──────────────────────────────────────────────────────────

# Lowercased section-header patterns we look for. Each maps to a logical section
# name we use internally.
SECTION_PATTERNS = [
    (r"(?:^|\n)\s*summary\s+(?:term sheet|of|of\s+the\s+merger)", "summary"),
    (r"(?:^|\n)\s*(?:background of the merger|background of the transaction)", "background"),
    (r"(?:^|\n)\s*(?:special committee|the special committee)\b", "special_committee"),
    (r"(?:^|\n)\s*(?:related party transactions?|certain relationships and related transactions)", "related_party"),
    (r"(?:^|\n)\s*(?:director compensation|compensation of directors)", "director_comp"),
    (r"(?:^|\n)\s*(?:opinion of|fairness opinion)", "fairness"),
    (r"(?:^|\n)\s*(?:proposals? to be voted|matters to be voted)", "voting"),
]


# ── HTML cleanup ─────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n{3,}")
_ENTITY_MAP = {
    "&nbsp;": " ", "&amp;": "&", "&quot;": '"', "&apos;": "'",
    "&lt;": "<", "&gt;": ">", "&#8217;": "'", "&#8220;": '"', "&#8221;": '"',
    "&#8211;": "-", "&#8212;": "--", "&#8226;": "*", "&rsquo;": "'",
    "&lsquo;": "'", "&ldquo;": '"', "&rdquo;": '"', "&mdash;": "--", "&ndash;": "-",
}


def html_to_text(html: str) -> str:
    """Convert filing HTML to plain text, preserving paragraph structure."""
    # Insert newlines for block-level tags before stripping
    block_tags = ["</p>", "</div>", "</tr>", "<br>", "<br/>", "<br />", "</h1>",
                  "</h2>", "</h3>", "</h4>", "</li>"]
    for t in block_tags:
        html = html.replace(t, t + "\n")

    text = _TAG_RE.sub("", html)
    for ent, ch in _ENTITY_MAP.items():
        text = text.replace(ent, ch)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


def split_into_sections(text: str) -> dict[str, str]:
    """Locate each known section by its header pattern and return its prose."""
    # Find all section start positions
    matches = []
    for pattern, name in SECTION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            matches.append((m.start(), name, m.group()))
    matches.sort()

    # Each section runs until the next match (or EOF)
    sections: dict[str, str] = {}
    for i, (start, name, _hdr) in enumerate(matches):
        end = matches[i+1][0] if i+1 < len(matches) else len(text)
        # Cap each section at 50KB to avoid swallowing the whole filing
        end = min(end, start + 50_000)
        sections[name] = text[start:end].strip()
    return sections


# ── Sub-extractors ───────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(
    r"\$\s?[\d,]+(?:\.\d+)?\s*(?:thousand|million|billion|M|B|K)?",
    re.IGNORECASE,
)


def extract_summary(text: str, max_paragraphs: int = 5) -> list[str]:
    """Pull the first few substantive paragraphs from the summary section."""
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
    return paragraphs[:max_paragraphs]


def extract_special_committee(text: str) -> list[SpecialCommitteeFact]:
    """Find names, dates, and counts in the special-committee section."""
    facts: list[SpecialCommitteeFact] = []

    # Number of members
    m = re.search(r"(?:committee of|composed of)\s+(?:\w+\s+){0,3}?(\d+|\w+)\s+(?:independent\s+)?directors?", text, re.IGNORECASE)
    if m:
        facts.append(SpecialCommitteeFact("members_count", m.group(1)))

    # Formation date
    m = re.search(r"(?:formed|established|formed by the board|established by the board)\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})", text, re.IGNORECASE)
    if m:
        facts.append(SpecialCommitteeFact("formed_date", m.group(1)))

    # Financial advisor
    m = re.search(r"(?:retained|engaged)\s+([A-Z][\w&,\s\.]+?)\s+(?:as|to act as)\s+(?:its\s+)?financial advisor", text)
    if m:
        facts.append(SpecialCommitteeFact("financial_advisor", m.group(1).strip()))

    # Legal advisor
    m = re.search(r"(?:retained|engaged)\s+([A-Z][\w&,\s\.]+?)\s+(?:as|to act as)\s+(?:its\s+)?legal (?:counsel|advisor)", text)
    if m:
        facts.append(SpecialCommitteeFact("legal_advisor", m.group(1).strip()))

    # Meetings count
    m = re.search(r"(?:met|held|convened)\s+(\d+|\w+)\s+(?:formal\s+)?meetings?", text, re.IGNORECASE)
    if m:
        facts.append(SpecialCommitteeFact("meetings_held", m.group(1)))

    return facts


def extract_related_parties(text: str, max_items: int = 20) -> list[RelatedPartyTransaction]:
    """Find related-party transaction descriptions."""
    items: list[RelatedPartyTransaction] = []
    # Split on paragraph breaks; look for paragraphs that mention dollar amounts
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
    for p in paragraphs:
        if len(items) >= max_items:
            break
        amounts = _AMOUNT_RE.findall(p)
        if not amounts:
            continue
        # First sentence as description
        first_sentence = re.split(r"(?<=[\.!?])\s+", p)[0][:300]
        # Try to identify the counterparty from the prose
        cp_match = re.search(r"\b(?:from|to|with|by)\s+([A-Z][\w&\.,\s]+?(?:Inc\.|LLC|LP|Ltd|Limited|Corp\.?|Company|Group|Holdings|Partners))\b", p)
        counterparty = cp_match.group(1).strip() if cp_match else "(unidentified)"
        items.append(RelatedPartyTransaction(
            counterparty=counterparty,
            description=first_sentence,
            amount=amounts[0] if amounts else None,
        ))
    return items


def extract_fairness_advisors(text: str) -> list[str]:
    """Find the financial advisors who issued fairness opinions."""
    advisors = set()
    for m in re.finditer(
        r"(?:opinion of|fairness opinion of|delivered (?:its|a) (?:fairness )?opinion (?:by|of)?\s*)\s*([A-Z][\w&,\s\.]+?(?:Inc\.|LLC|LP|Securities|Capital|Partners|Group|Co\.))",
        text
    ):
        adv = m.group(1).strip()
        if 4 <= len(adv) <= 80:
            advisors.add(adv)
    return sorted(advisors)


def extract_voting_proposals(text: str, max_items: int = 10) -> list[dict]:
    """Find numbered proposals to be voted on."""
    proposals = []
    for m in re.finditer(
        r"Proposal\s+(?:No\.\s*)?(\d+)[\.:]?\s*([A-Z][^\n]{20,200})",
        text,
    ):
        proposals.append({
            "number": int(m.group(1)),
            "title": m.group(2).strip(),
        })
        if len(proposals) >= max_items:
            break
    return proposals


# ── Top-level API ────────────────────────────────────────────────────────────

EDGAR_FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type={form}&dateb=&owner=include&count=40"
EDGAR_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{doc_name}"


def _accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


def _fetch_filing_text(cik: int, accession: str) -> tuple[str, str]:
    """Fetch the primary HTML document for a filing.

    Returns (form_type, plain_text).
    """
    acc_clean = _accession_no_dashes(accession)
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/index.json"
    try:
        idx = fetch(index_url, headers={"Accept": "application/json"}, cache_max_age=86400)
        idx_data = idx.json()
    except Exception as e:
        raise RuntimeError(f"Could not fetch filing index: {e}")

    items = idx_data.get("directory", {}).get("item", [])
    # Prefer the primary .htm file with the largest size, that isn't the index
    candidates = [it for it in items
                  if it.get("name", "").lower().endswith((".htm", ".html"))
                  and "index" not in it.get("name", "").lower()]
    if not candidates:
        raise RuntimeError("No HTML document found in filing index")

    candidates.sort(key=lambda it: int(it.get("size", 0) or 0), reverse=True)
    doc_name = candidates[0]["name"]
    doc_url = EDGAR_DOC_URL.format(cik=cik, acc_clean=acc_clean, doc_name=doc_name)

    doc = fetch(doc_url, cache_max_age=86400)
    text = html_to_text(doc.text())

    # Form type can sometimes be inferred from filename prefix
    form_type = ""
    if "defm14a" in doc_name.lower():
        form_type = "DEFM14A"
    elif "def14a" in doc_name.lower() or "defa14a" in doc_name.lower():
        form_type = "DEF 14A"
    elif "prer14a" in doc_name.lower():
        form_type = "PRER14A"
    elif "prem14a" in doc_name.lower():
        form_type = "PREM14A"

    return form_type, text


def parse_proxy(cik: int, accession: str) -> ProxyExtraction:
    """Pull and parse a proxy filing from SEC EDGAR.

    Parameters
    ----------
    cik : int
        Company CIK number.
    accession : str
        Accession number, with or without dashes, e.g. "0001140361-25-045199".

    Returns
    -------
    ProxyExtraction
        Structured extraction of the filing's substantive content.
    """
    form_type, text = _fetch_filing_text(cik, accession)

    extraction = ProxyExtraction(
        cik=cik, accession=accession, form_type=form_type,
        raw_text_length=len(text),
    )

    sections = split_into_sections(text)

    if "summary" in sections:
        extraction.summary_paragraphs = extract_summary(sections["summary"])

    if "special_committee" in sections:
        extraction.special_committee = extract_special_committee(sections["special_committee"])

    if "related_party" in sections:
        extraction.related_party_transactions = extract_related_parties(sections["related_party"])

    if "fairness" in sections:
        extraction.fairness_opinion_advisors = extract_fairness_advisors(sections["fairness"])

    if "voting" in sections:
        extraction.voting_proposals = extract_voting_proposals(sections["voting"])

    return extraction


def summarize_extraction(ex: ProxyExtraction) -> str:
    """Human-readable summary of a proxy extraction."""
    lines = [
        f"Proxy extraction: {ex.form_type or '(form unknown)'}",
        f"  CIK: {ex.cik}  Accession: {ex.accession}",
        f"  Raw text length: {ex.raw_text_length:,} characters",
        "",
    ]

    if ex.summary_paragraphs:
        lines.append("SUMMARY (first paragraph):")
        lines.append(f"  {ex.summary_paragraphs[0][:300]}...")
        lines.append("")

    if ex.special_committee:
        lines.append("SPECIAL COMMITTEE:")
        for fact in ex.special_committee:
            lines.append(f"  {fact.field_name:<22} {fact.value}")
        lines.append("")

    if ex.fairness_opinion_advisors:
        lines.append("FAIRNESS OPINION ADVISORS:")
        for adv in ex.fairness_opinion_advisors:
            lines.append(f"  - {adv}")
        lines.append("")

    if ex.related_party_transactions:
        lines.append(f"RELATED-PARTY TRANSACTIONS ({len(ex.related_party_transactions)} found):")
        for rpt in ex.related_party_transactions[:5]:
            amt = f" [{rpt.amount}]" if rpt.amount else ""
            lines.append(f"  - {rpt.counterparty}{amt}")
            lines.append(f"      {rpt.description[:150]}...")
        if len(ex.related_party_transactions) > 5:
            lines.append(f"  ... ({len(ex.related_party_transactions) - 5} more)")
        lines.append("")

    if ex.voting_proposals:
        lines.append(f"VOTING PROPOSALS ({len(ex.voting_proposals)}):")
        for p in ex.voting_proposals:
            lines.append(f"  {p['number']}. {p['title']}")

    return "\n".join(lines)
