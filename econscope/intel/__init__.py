"""Intelligence module: connection discovery, forensic analysis, governance parsing.

The `intel` layer is where ECONSCOPE moves from "pull and store" to "discover and
interpret." Each submodule answers a specific investigative question:

- `network`  — given an entity, who else is connected to it?
- `forensic` — given a company's financials, are there manipulation flags?
- `proxies`  — given a merger filing, what does the governance structure look like?
- `insiders` — given a ticker, what are insiders doing with their shares?
- `http`     — shared HTTP layer with retry, backoff, caching, and graceful failure
"""

from econscope.intel.http import fetch, fetch_json, RetryableHTTPError
from econscope.intel.network import (
    discover,
    edgar_fts,
    edgar_holders,
    wiki_expand,
    NetworkGraph,
)
from econscope.intel.forensic import (
    beneish_m_score,
    altman_z_score,
    sloan_accruals,
    piotroski_f_score,
    going_concern_score,
    ForensicReport,
)
from econscope.intel.textdiff import (
    textdiff_report,
    summarize_textdiff,
    jaccard_similarity,
    TextDiffReport,
    SectionDiff,
)

__all__ = [
    "fetch",
    "fetch_json",
    "RetryableHTTPError",
    "discover",
    "edgar_fts",
    "edgar_holders",
    "wiki_expand",
    "NetworkGraph",
    "beneish_m_score",
    "altman_z_score",
    "sloan_accruals",
    "ForensicReport",
    "textdiff_report",
    "summarize_textdiff",
    "jaccard_similarity",
    "TextDiffReport",
    "SectionDiff",
]
