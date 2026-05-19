"""Forensic accounting: Beneish M-score, Altman Z-score, Sloan accruals.

These are classical screening tools from the academic forensic-accounting
literature. Each one combines several financial ratios into a single score that
correlates with a specific kind of trouble:

- Beneish M-score (Beneish 1999, Financial Analysts Journal): earnings manipulation
- Altman Z-score (Altman 1968, J. of Finance): bankruptcy within 2 years
- Sloan accruals ratio (Sloan 1996, The Accounting Review): earnings quality

None of these is a verdict — they are screening tools. A red-flag M-score tells
you the financial profile is statistically similar to known earnings
manipulators, not that the company is manipulating earnings. Same logic for
Z and Sloan.

This module pulls XBRL data from SEC EDGAR, computes the scores year by year,
and returns a structured `ForensicReport`. It's the in-platform version of the
standalone `forensic-econ` Go CLI.

References
----------
Beneish, M. D. (1999). "The Detection of Earnings Manipulation." Financial Analysts
    Journal, 55(5), 24-36.
Altman, E. I. (1968). "Financial Ratios, Discriminant Analysis and the Prediction
    of Corporate Bankruptcy." The Journal of Finance, 23(4), 589-609.
Sloan, R. G. (1996). "Do Stock Prices Fully Reflect Information in Accruals and
    Cash Flows About Future Earnings?" The Accounting Review, 71(3), 289-315.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

from econscope.intel.http import fetch_json


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class YearlyScore:
    """One year of forensic scores."""
    fiscal_year: int
    beneish_m: Optional[float] = None
    altman_z: Optional[float] = None
    sloan_accruals: Optional[float] = None
    flags: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)


@dataclass
class ForensicReport:
    """Multi-year forensic analysis for a single company."""
    cik: int
    company: str
    years: list[YearlyScore] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "cik": self.cik,
            "company": self.company,
            "years": [asdict(y) for y in self.years],
            "notes": self.notes,
        }, indent=2, default=str)


# ── XBRL data fetcher ─────────────────────────────────────────────────────────

EDGAR_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# XBRL tags we need for the three scores. Multiple tags per concept because
# companies disclose under slightly different names.
TAG_MAP = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cost_of_goods": ["CostOfGoodsSold", "CostOfGoodsAndServicesSold", "CostOfRevenue"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "depreciation": ["Depreciation", "DepreciationDepletionAndAmortization",
                     "DepreciationAndAmortization"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "cash_from_ops": ["NetCashProvidedByUsedInOperatingActivities"],
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "total_liabilities": ["Liabilities"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "accounts_receivable": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "stockholders_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}


def _fetch_company_facts(cik: int) -> dict:
    """Pull all XBRL facts for a CIK from SEC EDGAR."""
    url = EDGAR_FACTS_URL.format(cik=cik)
    return fetch_json(url, cache_max_age=86400)


def _extract_annual_series(facts: dict, tag_candidates: list[str]) -> dict[int, float]:
    """For each fiscal year, get the FY value for the first tag that has one.

    Returns {year: value}.
    """
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tag_candidates:
        if tag not in usgaap:
            continue
        units = usgaap[tag].get("units", {})
        # Prefer USD; fall back to whatever's available
        unit_key = next((k for k in units if k.upper() in ("USD", "USD/SHARES")), None)
        if not unit_key:
            unit_key = next(iter(units), None)
        if not unit_key:
            continue
        out: dict[int, float] = {}
        for entry in units[unit_key]:
            if entry.get("fp") == "FY" and entry.get("form", "").startswith("10-K"):
                fy = entry.get("fy")
                val = entry.get("val")
                if fy and val is not None:
                    out[int(fy)] = float(val)
        if out:
            return out
    return {}


def _gather_inputs(facts: dict) -> dict[int, dict]:
    """Build a {year: {concept: value}} table from XBRL facts."""
    series_by_concept = {c: _extract_annual_series(facts, tags) for c, tags in TAG_MAP.items()}
    years = sorted(set().union(*[set(s.keys()) for s in series_by_concept.values()]))
    return {
        y: {c: series_by_concept[c].get(y) for c in TAG_MAP}
        for y in years
    }


# ── Beneish M-score ──────────────────────────────────────────────────────────

def beneish_m_score(curr: dict, prev: dict) -> Optional[float]:
    """Compute Beneish M-score from current-year and prior-year inputs.

    M = -4.84 + 0.92*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI + 0.115*DEPI
        - 0.172*SGAI + 4.679*TATA - 0.327*LVGI

    Threshold: M > -1.78 indicates statistical similarity to known manipulators.

    Returns None if required inputs are missing.
    """
    try:
        # DSRI: Days Sales in Receivables Index
        ar_t = curr["accounts_receivable"]; ar_p = prev["accounts_receivable"]
        rev_t = curr["revenue"]; rev_p = prev["revenue"]
        if not all(x is not None and x != 0 for x in [ar_t, ar_p, rev_t, rev_p]):
            return None
        dsri = (ar_t / rev_t) / (ar_p / rev_p)

        # GMI: Gross Margin Index
        cogs_t = curr["cost_of_goods"] or 0
        cogs_p = prev["cost_of_goods"] or 0
        gm_t = (rev_t - cogs_t) / rev_t if rev_t else 0
        gm_p = (rev_p - cogs_p) / rev_p if rev_p else 0
        if gm_t == 0:
            return None
        gmi = gm_p / gm_t

        # AQI: Asset Quality Index
        ta_t = curr["total_assets"]; ta_p = prev["total_assets"]
        ca_t = curr["current_assets"] or 0; ca_p = prev["current_assets"] or 0
        ppe_t = curr["ppe_net"] or 0; ppe_p = prev["ppe_net"] or 0
        if not ta_t or not ta_p:
            return None
        non_quality_t = 1 - (ca_t + ppe_t) / ta_t
        non_quality_p = 1 - (ca_p + ppe_p) / ta_p
        aqi = non_quality_t / non_quality_p if non_quality_p else 1

        # SGI: Sales Growth Index
        sgi = rev_t / rev_p

        # DEPI: Depreciation Index
        dep_t = curr["depreciation"] or 0
        dep_p = prev["depreciation"] or 0
        depi = (dep_p / (ppe_p + dep_p)) / (dep_t / (ppe_t + dep_t)) if (dep_t and ppe_t + dep_t) else 1

        # SGAI: SG&A Index
        sga_t = curr["sga"] or 0
        sga_p = prev["sga"] or 0
        sgai = (sga_t / rev_t) / (sga_p / rev_p) if (sga_p and rev_p) else 1

        # TATA: Total Accruals to Total Assets
        ni_t = curr["net_income"] or 0
        cfo_t = curr["cash_from_ops"] or 0
        tata = (ni_t - cfo_t) / ta_t

        # LVGI: Leverage Index
        tl_t = curr["total_liabilities"] or 0
        tl_p = prev["total_liabilities"] or 0
        lvgi = (tl_t / ta_t) / (tl_p / ta_p) if ta_p else 1

        m = (-4.84 + 0.92*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi
             + 0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi)
        if not math.isfinite(m):
            return None
        return m
    except (KeyError, TypeError, ZeroDivisionError):
        return None


# ── Altman Z-score ───────────────────────────────────────────────────────────

def altman_z_score(inputs: dict, market_value_equity: Optional[float] = None) -> Optional[float]:
    """Compute Altman Z-score (original 1968 version) for public manufacturers.

    Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5

    Where:
      X1 = working capital / total assets
      X2 = retained earnings / total assets
      X3 = EBIT / total assets
      X4 = market value of equity / total liabilities
      X5 = sales / total assets

    Thresholds:
      Z > 2.99: safe
      1.81 < Z < 2.99: gray zone
      Z < 1.81: distress

    If market_value_equity is None, falls back to book equity (Z-prime variant).
    """
    try:
        ta = inputs.get("total_assets")
        if not ta:
            return None
        ca = inputs.get("current_assets") or 0
        cl = inputs.get("current_liabilities") or 0
        wc = ca - cl
        re_ = inputs.get("retained_earnings") or 0
        oi = inputs.get("operating_income") or inputs.get("net_income") or 0  # EBIT proxy
        tl = inputs.get("total_liabilities") or 0
        rev = inputs.get("revenue") or 0
        eq = market_value_equity if market_value_equity is not None else (inputs.get("stockholders_equity") or 0)

        if tl == 0:
            return None

        x1 = wc / ta
        x2 = re_ / ta
        x3 = oi / ta
        x4 = eq / tl
        x5 = rev / ta
        z = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5
        if not math.isfinite(z):
            return None
        return z
    except (TypeError, ZeroDivisionError):
        return None


# ── Sloan accruals ───────────────────────────────────────────────────────────

def sloan_accruals(inputs: dict) -> Optional[float]:
    """Compute Sloan accruals ratio: (NI - CFO) / |total assets|.

    High values mean earnings are driven more by accounting accruals than by
    realized cash flow, which is associated with future earnings reversion.
    """
    try:
        ni = inputs.get("net_income")
        cfo = inputs.get("cash_from_ops")
        ta = inputs.get("total_assets")
        if None in (ni, cfo, ta) or ta == 0:
            return None
        return (ni - cfo) / abs(ta)
    except (TypeError, ZeroDivisionError):
        return None


# ── Piotroski F-Score ────────────────────────────────────────────────────────

def piotroski_f_score(curr: dict, prev: Optional[dict] = None) -> Optional[int]:
    """Compute Piotroski F-Score (Piotroski 2000): 0-9 financial-strength score.

    Sums 9 binary tests across three dimensions:

    Profitability (4 tests):
      F1: Net income > 0
      F2: Cash flow from operations > 0
      F3: ROA improved vs prior year (requires prev)
      F4: Cash flow from ops > net income (quality of earnings)

    Leverage / liquidity (3 tests, all require prev):
      F5: Long-term debt to assets decreased
      F6: Current ratio improved
      F7: No new shares issued (proxy: equity didn't grow excluding retained earnings)

    Operating efficiency (2 tests, both require prev):
      F8: Gross margin improved
      F9: Asset turnover (sales / assets) improved

    Thresholds:
      F-Score >= 8: strong (top quintile typically outperforms)
      F-Score <= 2: weak (bottom quintile typically underperforms)

    If prev is None, only F1, F2, F4 are computed (max score 3).
    """
    try:
        score = 0
        ta = curr.get("total_assets") or 0
        ni = curr.get("net_income") or 0
        cfo = curr.get("cash_from_ops") or 0
        rev = curr.get("revenue") or 0

        # F1: net income > 0
        if ni > 0: score += 1
        # F2: CFO > 0
        if cfo > 0: score += 1
        # F4: CFO > NI (cash-quality of earnings)
        if cfo > ni: score += 1

        if prev is None:
            return score

        ta_p = prev.get("total_assets") or 0
        ni_p = prev.get("net_income") or 0
        rev_p = prev.get("revenue") or 0
        ltd = curr.get("long_term_debt") or 0
        ltd_p = prev.get("long_term_debt") or 0
        ca = curr.get("current_assets") or 0
        cl = curr.get("current_liabilities") or 0
        ca_p = prev.get("current_assets") or 0
        cl_p = prev.get("current_liabilities") or 0
        cogs = curr.get("cost_of_goods") or 0
        cogs_p = prev.get("cost_of_goods") or 0
        eq = curr.get("stockholders_equity") or 0
        eq_p = prev.get("stockholders_equity") or 0

        # F3: ROA improved
        roa = ni / ta if ta else 0
        roa_p = ni_p / ta_p if ta_p else 0
        if roa > roa_p: score += 1

        # F5: LTD / assets decreased
        if ta and ta_p:
            if (ltd / ta) < (ltd_p / ta_p): score += 1

        # F6: current ratio improved
        if cl and cl_p:
            if (ca / cl) > (ca_p / cl_p): score += 1

        # F7: equity didn't grow (proxy for no equity issuance — imperfect)
        if eq <= eq_p * 1.05: score += 1

        # F8: gross margin improved
        gm = (rev - cogs) / rev if rev else 0
        gm_p = (rev_p - cogs_p) / rev_p if rev_p else 0
        if gm > gm_p: score += 1

        # F9: asset turnover improved
        at_ = rev / ta if ta else 0
        at_p = rev_p / ta_p if ta_p else 0
        if at_ > at_p: score += 1

        return score
    except (TypeError, ZeroDivisionError):
        return None


# ── Going-concern textual classifier ─────────────────────────────────────────

_GC_PHRASES = [
    "substantial doubt about",
    "ability to continue as a going concern",
    "going concern qualification",
    "raises substantial doubt",
    "material uncertainty related to going concern",
    "may not be able to continue as a going concern",
]


def going_concern_score(text: str) -> dict:
    """Simple keyword-based going-concern classifier (Hedback 2025 + PCAOB AS 3105).

    Counts occurrences of canonical going-concern trigger phrases in the
    provided text (typically Item 1A risk factors + Item 7 MD&A + auditor's
    report). Returns a dict with the count, a boolean "flagged", and the
    phrases that hit.

    This is a screening tool, not a verdict — the same phrases sometimes appear
    as boilerplate "we believe we will be able to continue" denials. The score
    is most informative when applied year-over-year in textdiff.
    """
    if not text:
        return {"flagged": False, "phrase_count": 0, "hits": []}
    text_lc = text.lower()
    hits = [p for p in _GC_PHRASES if p in text_lc]
    return {
        "flagged": len(hits) > 0,
        "phrase_count": sum(text_lc.count(p) for p in _GC_PHRASES),
        "hits": hits,
    }


# ── Orchestration ────────────────────────────────────────────────────────────

def _flag_year(y: YearlyScore) -> None:
    """Annotate a year with red/yellow flags based on score thresholds."""
    if y.beneish_m is not None:
        if y.beneish_m > -1.78:
            y.flags.append("beneish_above_threshold")
    if y.altman_z is not None:
        if y.altman_z < 1.81:
            y.flags.append("altman_distress")
        elif y.altman_z < 2.99:
            y.flags.append("altman_gray_zone")
    if y.sloan_accruals is not None:
        if y.sloan_accruals > 0.10:
            y.flags.append("sloan_high_accruals")
    pf = y.inputs.get("_piotroski_f_score") if y.inputs else None
    if pf is not None:
        if pf <= 2:
            y.flags.append("piotroski_weak")
        elif pf >= 8:
            y.flags.append("piotroski_strong")


def forensic_report(cik: int) -> ForensicReport:
    """Pull XBRL facts for a CIK and compute all three scores for every available year."""
    facts = _fetch_company_facts(cik)
    company = facts.get("entityName", f"CIK {cik}")
    inputs_by_year = _gather_inputs(facts)

    report = ForensicReport(cik=cik, company=company)

    sorted_years = sorted(inputs_by_year.keys())
    for i, y in enumerate(sorted_years):
        curr = inputs_by_year[y]
        prev = inputs_by_year[sorted_years[i-1]] if i > 0 else None

        ys = YearlyScore(fiscal_year=y, inputs=curr)
        ys.altman_z = altman_z_score(curr)
        ys.sloan_accruals = sloan_accruals(curr)
        pf = piotroski_f_score(curr, prev)
        if pf is not None:
            ys.inputs["_piotroski_f_score"] = pf
        if prev:
            ys.beneish_m = beneish_m_score(curr, prev)
        _flag_year(ys)
        report.years.append(ys)

    if not report.years:
        report.notes.append("No fiscal-year XBRL data found. Company may be too new or non-US.")

    return report


def summarize_report(report: ForensicReport) -> str:
    """Human-readable forensic summary."""
    lines = [
        f"Forensic Report: {report.company} (CIK {report.cik})",
        f"  Years analyzed: {len(report.years)}",
        "",
        f"{'Year':<6} {'Beneish M':>11} {'Altman Z':>11} {'Sloan':>9}  Flags",
        "-" * 70,
    ]
    for y in report.years:
        m = f"{y.beneish_m:>11.2f}" if y.beneish_m is not None else f"{'n/a':>11}"
        z = f"{y.altman_z:>11.2f}" if y.altman_z is not None else f"{'n/a':>11}"
        s = f"{y.sloan_accruals:>9.3f}" if y.sloan_accruals is not None else f"{'n/a':>9}"
        flags = ", ".join(y.flags) if y.flags else ""
        lines.append(f"{y.fiscal_year:<6} {m} {z} {s}  {flags}")
    if report.notes:
        lines.append("")
        for n in report.notes:
            lines.append(f"  Note: {n}")
    return "\n".join(lines)
