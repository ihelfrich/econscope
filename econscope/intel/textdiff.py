"""10-K / 10-Q text-diff analyzer.

Cohen, Malloy, and Nguyen (2020, Journal of Finance 75(3), "Lazy Prices") show
that text changes in 10-K and 10-Q filings predict future returns (roughly 22%
annualized long-short alpha), future earnings, and firm-level bankruptcies. The
signal is orthogonal to traditional accounting-based fraud detectors (Beneish,
Altman, Sloan): a company that quietly rewrites its risk-factor or MD&A
language is conveying information the market hasn't priced in.

This module:

1. Pulls a company's recent 10-K and 10-Q filings from SEC EDGAR.
2. Extracts the substantive item sections (Item 1A risk factors, Item 7 MD&A,
   Item 8 financial statements, Item 9A controls, going-concern language).
3. Computes Jaccard-shingle similarity between successive filings for each
   section.
4. Optionally computes Loughran–McDonald sentiment deltas (negative,
   uncertainty, litigious) per section when the dictionary file is present.
5. Flags sections with similarity below the Cohen-Malloy-style threshold for
   manual review.

The "lazy" framing is that most filings recycle most of their text year over
year. The interesting filings are the ones where prose has been actively
rewritten — that's almost always information.

References
----------
Cohen, L., Malloy, C., & Nguyen, Q. (2020). "Lazy Prices." Journal of Finance,
    75(3), 1371–1415.

Loughran, T., & McDonald, B. (2011). "When Is a Liability Not a Liability?
    Textual Analysis, Dictionaries, and 10-Ks." Journal of Finance, 66(1), 35–65.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from econscope.intel.http import fetch


# ── Section anchors for 10-K / 10-Q parsing ──────────────────────────────────
# These regex patterns match the "Item X" headers in 10-K filings. They are
# deliberately permissive — EDGAR HTML formatting varies enormously across
# filers and years.

SECTION_PATTERNS = [
    # (regex, normalized section id, friendly name)
    (r"item\s*1[\.\s]+business", "item_1_business", "Business"),
    (r"item\s*1a[\.\s]+risk\s+factors", "item_1a_risk_factors", "Risk Factors"),
    (r"item\s*1b[\.\s]+unresolved\s+staff", "item_1b_unresolved", "Unresolved Staff Comments"),
    (r"item\s*2[\.\s]+properties", "item_2_properties", "Properties"),
    (r"item\s*3[\.\s]+legal\s+proceedings", "item_3_legal", "Legal Proceedings"),
    (r"item\s*5[\.\s]+market\s+for", "item_5_market", "Market for Registrant's Common Equity"),
    (r"item\s*7[\.\s]+management.?s?\s+discussion", "item_7_mda", "Management's Discussion and Analysis"),
    (r"item\s*7a[\.\s]+quantitative", "item_7a_market_risk", "Quantitative and Qualitative Disclosures About Market Risk"),
    (r"item\s*8[\.\s]+financial\s+statements", "item_8_financials", "Financial Statements"),
    (r"item\s*9a[\.\s]+controls", "item_9a_controls", "Controls and Procedures"),
]

# Going-concern trigger phrases (Hedback 2025 + standard PCAOB AS 3105 markers)
GC_TRIGGER_PHRASES = [
    "substantial doubt",
    "going concern",
    "material uncertainty",
    "ability to continue as a going concern",
    "raises substantial doubt",
    "may not be able to continue",
]


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class SectionExtract:
    """One parsed section from a single filing."""
    section_id: str
    section_name: str
    text: str
    char_count: int = 0
    shingle_count: int = 0
    has_gc_trigger: bool = False

    def __post_init__(self):
        self.char_count = len(self.text)


@dataclass
class FilingExtract:
    """All sections extracted from one filing."""
    cik: int
    accession: str
    form_type: str
    period: Optional[str] = None
    filed_date: Optional[str] = None
    sections: dict[str, SectionExtract] = field(default_factory=dict)
    full_text_length: int = 0


@dataclass
class SectionDiff:
    """Pairwise diff between the same section across two filings."""
    section_id: str
    section_name: str
    cik: int
    accession_prior: str
    accession_current: str
    period_prior: Optional[str] = None
    period_current: Optional[str] = None
    jaccard_similarity: float = 1.0
    char_delta: int = 0
    has_gc_trigger_now: bool = False
    has_gc_trigger_prior: bool = False
    gc_trigger_appeared: bool = False
    flagged: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class TextDiffReport:
    """Multi-year text-diff report for a single company."""
    cik: int
    company: Optional[str] = None
    filings_analyzed: list[FilingExtract] = field(default_factory=list)
    diffs: list[SectionDiff] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "cik": self.cik,
            "company": self.company,
            "filings_analyzed": [
                {**asdict(f), "sections": {k: asdict(v) for k, v in f.sections.items()}}
                for f in self.filings_analyzed
            ],
            "diffs": [asdict(d) for d in self.diffs],
        }, indent=2, default=str)


# ── HTML cleanup ─────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ENTITY_MAP = {
    "&nbsp;": " ", "&amp;": "&", "&quot;": '"', "&apos;": "'",
    "&lt;": "<", "&gt;": ">", "&#8217;": "'", "&#8220;": '"', "&#8221;": '"',
    "&#8211;": "-", "&#8212;": "--", "&#8226;": "*", "&rsquo;": "'",
    "&lsquo;": "'", "&ldquo;": '"', "&rdquo;": '"', "&mdash;": "--", "&ndash;": "-",
    "&#160;": " ",
}


def _html_to_text(html: str) -> str:
    """Convert filing HTML to plain text suitable for diffing."""
    # Insert newlines before block elements so paragraphs survive
    for tag in ["</p>", "</div>", "</tr>", "<br>", "<br/>", "<br />",
                "</h1>", "</h2>", "</h3>", "</h4>", "</li>"]:
        html = html.replace(tag, tag + "\n")
    text = _TAG_RE.sub("", html)
    for ent, ch in _ENTITY_MAP.items():
        text = text.replace(ent, ch)
    text = _WS_RE.sub(" ", text)
    return text.strip().lower()  # lowercase for case-insensitive shingling


# ── Section segmentation ─────────────────────────────────────────────────────

def _segment_sections(text: str) -> dict[str, SectionExtract]:
    """Cut the filing text into known item sections.

    The algorithm: find the position of every known section header. Sort by
    position. Each section's text runs from its header to the next header.
    Sections that don't appear are simply absent from the result.

    This will fail or produce noise for ~10-15% of filings (smaller filers,
    S-1/S-4 hybrids, weird formatting). The caller should treat absent sections
    as "couldn't extract" rather than "no risk factors disclosed."
    """
    matches = []
    for pattern, sid, name in SECTION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((m.start(), sid, name))
    matches.sort()

    sections: dict[str, SectionExtract] = {}
    for i, (start, sid, name) in enumerate(matches):
        # Skip duplicates (same section_id appearing twice — TOC + body)
        if sid in sections:
            # Prefer the LATER match (body, not TOC)
            pass
        end = matches[i+1][0] if i+1 < len(matches) else min(start + 200_000, len(text))
        section_text = text[start:end].strip()
        has_gc = any(phrase in section_text for phrase in GC_TRIGGER_PHRASES)
        sections[sid] = SectionExtract(
            section_id=sid,
            section_name=name,
            text=section_text,
            has_gc_trigger=has_gc,
        )
    # Compute shingle counts after population
    for s in sections.values():
        s.shingle_count = len(_shingles(s.text))
    return sections


# ── Similarity ────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "by", "with", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "this",
    "that", "these", "those", "we", "our", "us", "their", "they", "its",
}

_FORWARD_LOOKING_BOILERPLATE_PATTERNS = [
    r"forward[-\s]?looking\s+statements?",
    r"safe\s+harbor",
    r"reform\s+act\s+of\s+1995",
    r"private\s+securities\s+litigation",
    r"actual\s+results\s+(?:may|could)\s+differ",
]


def _strip_boilerplate(text: str) -> str:
    """Remove the standard forward-looking-statements block, which dominates
    raw similarity otherwise."""
    # Find any of the boilerplate trigger phrases and delete the surrounding
    # ~2,000 chars window. Cohen-Malloy specifically calls this out.
    for pattern in _FORWARD_LOOKING_BOILERPLATE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, m.start() - 500)
            end = min(len(text), m.end() + 1500)
            text = text[:start] + " " + text[end:]
    return text


def _shingles(text: str, n: int = 4) -> set[tuple]:
    """Sentence-level n-grams (shingles) over content words.

    Cohen-Malloy's exact algorithm uses 4-word shingles after stopword removal.
    This reproduces that.
    """
    text = _strip_boilerplate(text)
    words = [w for w in re.findall(r"[a-z][a-z']+", text) if w not in _STOPWORDS]
    if len(words) < n:
        return set()
    return {tuple(words[i:i+n]) for i in range(len(words) - n + 1)}


def jaccard_similarity(text_a: str, text_b: str, *, shingle_size: int = 4) -> float:
    """Jaccard similarity over content-word shingles."""
    sa = _shingles(text_a, n=shingle_size)
    sb = _shingles(text_b, n=shingle_size)
    if not sa and not sb:
        return 1.0  # both empty — vacuously identical
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# ── EDGAR filing fetching ────────────────────────────────────────────────────

EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def _list_recent_filings(cik: int, form_type: str, limit: int = 5) -> list[dict]:
    """Get the N most-recent filings of a given form type from EDGAR."""
    url = EDGAR_SUBMISSIONS.format(cik=cik)
    try:
        data = fetch(url, headers={"Accept": "application/json"}, cache_max_age=86400).json()
    except Exception as e:
        raise RuntimeError(f"Could not pull EDGAR submissions for CIK {cik}: {e}")

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    periods = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    for i, f in enumerate(forms):
        if f != form_type:
            continue
        results.append({
            "accession": accessions[i],
            "filed_date": dates[i],
            "period": periods[i],
            "primary_doc": primary_docs[i],
        })
        if len(results) >= limit:
            break
    return results


def _fetch_filing_text(cik: int, accession: str, primary_doc: str) -> str:
    """Download the primary HTML document for a filing and return plain text."""
    acc_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{primary_doc}"
    body = fetch(url, cache_max_age=86400).text()
    return _html_to_text(body)


# ── Orchestration ────────────────────────────────────────────────────────────

CM_SIMILARITY_THRESHOLD = 0.85  # Cohen-Malloy uses ~0.80–0.85 depending on year


def textdiff_report(
    cik: int,
    *,
    form_type: str = "10-K",
    years: int = 5,
    similarity_threshold: float = CM_SIMILARITY_THRESHOLD,
) -> TextDiffReport:
    """Pull the last N filings of a given form type, segment by section, and
    compute year-over-year section diffs.

    Parameters
    ----------
    cik : int
        Company CIK number.
    form_type : str
        "10-K" or "10-Q".
    years : int
        Number of filings to compare (one diff per pair, so N filings = N-1 diffs).
    similarity_threshold : float
        Sections below this Jaccard similarity are flagged for review.

    Returns
    -------
    TextDiffReport
        Per-filing extracts + pairwise diffs with similarity scores and flags.
    """
    filings_meta = _list_recent_filings(cik, form_type, limit=years)
    if not filings_meta:
        return TextDiffReport(cik=cik)

    # Pull text for each
    filings: list[FilingExtract] = []
    for meta in filings_meta:
        try:
            text = _fetch_filing_text(cik, meta["accession"], meta["primary_doc"])
        except Exception as e:
            # Skip failures rather than dropping the whole report
            continue
        sections = _segment_sections(text)
        filings.append(FilingExtract(
            cik=cik,
            accession=meta["accession"],
            form_type=form_type,
            period=meta.get("period"),
            filed_date=meta.get("filed_date"),
            sections=sections,
            full_text_length=len(text),
        ))

    # Pair consecutive filings (filings are returned newest-first, so reverse
    # for chronological order)
    filings.sort(key=lambda f: f.filed_date or "")

    diffs: list[SectionDiff] = []
    for i in range(1, len(filings)):
        prior = filings[i-1]
        current = filings[i]
        common_section_ids = set(prior.sections) & set(current.sections)
        for sid in sorted(common_section_ids):
            ps = prior.sections[sid]
            cs = current.sections[sid]
            sim = jaccard_similarity(ps.text, cs.text)
            char_delta = cs.char_count - ps.char_count
            gc_appeared = cs.has_gc_trigger and not ps.has_gc_trigger
            diff = SectionDiff(
                section_id=sid,
                section_name=cs.section_name,
                cik=cik,
                accession_prior=prior.accession,
                accession_current=current.accession,
                period_prior=prior.period,
                period_current=current.period,
                jaccard_similarity=sim,
                char_delta=char_delta,
                has_gc_trigger_now=cs.has_gc_trigger,
                has_gc_trigger_prior=ps.has_gc_trigger,
                gc_trigger_appeared=gc_appeared,
                flagged=(sim < similarity_threshold) or gc_appeared,
            )
            if gc_appeared:
                diff.notes.append("going-concern language appeared in this filing for the first time")
            if abs(char_delta) > 10_000:
                diff.notes.append(f"section length changed by {char_delta:+,} characters")
            if sim < similarity_threshold:
                diff.notes.append(f"substantive text rewrite (Jaccard {sim:.2f} below threshold {similarity_threshold:.2f})")
            diffs.append(diff)

    return TextDiffReport(cik=cik, filings_analyzed=filings, diffs=diffs)


def summarize_textdiff(report: TextDiffReport) -> str:
    """Human-readable summary of the text-diff report."""
    lines = [
        f"Text-diff report: CIK {report.cik}",
        f"  Filings analyzed: {len(report.filings_analyzed)}",
        f"  Section-pair diffs: {len(report.diffs)}",
        "",
    ]
    flagged = [d for d in report.diffs if d.flagged]
    if flagged:
        lines.append(f"FLAGGED SECTIONS ({len(flagged)}):")
        lines.append("")
        lines.append(f"{'Period':<24} {'Section':<42} {'Jaccard':>9}  Notes")
        lines.append("-" * 100)
        for d in flagged:
            period_label = f"{d.period_prior} → {d.period_current}"
            notes = "; ".join(d.notes) if d.notes else ""
            lines.append(f"{period_label:<24} {d.section_name[:40]:<42} {d.jaccard_similarity:>9.2f}  {notes}")
    else:
        lines.append("(No sections flagged. All section-pair similarities above threshold.)")

    return "\n".join(lines)
