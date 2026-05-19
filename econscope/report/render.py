"""Render structured analyses into Markdown and PDF.

The bottom of the report pipeline: take a ForensicReport, NetworkGraph, or
arbitrary markdown, and produce a polished deliverable.

PDF rendering goes through xelatex if it's available (system fonts), with a
fallback to pandoc's default LaTeX engine if not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from econscope.intel.forensic import ForensicReport, summarize_report
from econscope.intel.network import NetworkGraph, summarize


def markdown_to_pdf(
    markdown: str,
    *,
    output_path: str,
    title: Optional[str] = None,
    use_xelatex: bool = True,
) -> str:
    """Render a Markdown string to PDF via pandoc.

    Adds an automatic header with title. Uses xelatex if available (so we can
    use system fonts like Helvetica Neue). Falls back to default LaTeX engine
    if xelatex isn't found.
    """
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc not found in PATH. Install it from https://pandoc.org")

    # Ensure LaTeX binaries are in PATH for xelatex
    if use_xelatex:
        os.environ["PATH"] = "/Library/TeX/texbin:" + os.environ.get("PATH", "")

    full_md = ""
    if title:
        full_md += f"---\ntitle: {title}\n---\n\n"
    full_md += markdown

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(full_md)
        md_path = f.name

    try:
        cmd = ["pandoc", md_path, "-o", output_path]
        if use_xelatex and shutil.which("xelatex"):
            cmd.extend(["--pdf-engine=xelatex"])
        cmd.extend(["-V", "geometry:margin=1in", "-V", "mainfont=Helvetica Neue"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"pandoc failed: {result.stderr}")
    finally:
        Path(md_path).unlink(missing_ok=True)

    return output_path


def render_forensic_report(
    report: ForensicReport,
    *,
    output_path: str,
    format: str = "markdown",
) -> str:
    """Render a ForensicReport as Markdown or PDF.

    Format options: "markdown", "pdf".
    """
    md_parts = [
        f"# Forensic accounting report: {report.company}",
        f"**CIK:** {report.cik}  **Years analyzed:** {len(report.years)}",
        "",
        "## Scores by year",
        "",
        "| Year | Beneish M | Altman Z | Sloan accruals | Flags |",
        "|------|-----------|----------|----------------|-------|",
    ]
    for y in report.years:
        m = f"{y.beneish_m:.2f}" if y.beneish_m is not None else "n/a"
        z = f"{y.altman_z:.2f}" if y.altman_z is not None else "n/a"
        s = f"{y.sloan_accruals:.3f}" if y.sloan_accruals is not None else "n/a"
        flags = ", ".join(y.flags) if y.flags else "—"
        md_parts.append(f"| {y.fiscal_year} | {m} | {z} | {s} | {flags} |")

    md_parts += [
        "",
        "## Interpretation",
        "",
        "These are **screening tools**, not verdicts. A red-flag M-score means the "
        "financial profile is statistically similar to known earnings manipulators, "
        "not that the company is manipulating. Same for the others.",
        "",
        "**Beneish M-score thresholds:**",
        "- M > −1.78: above the academic manipulation threshold (yellow flag)",
        "- M ≤ −1.78: below the threshold (no flag)",
        "",
        "**Altman Z-score thresholds:**",
        "- Z > 2.99: safe zone",
        "- 1.81 < Z < 2.99: gray zone",
        "- Z < 1.81: distress zone (bankruptcy within 2 years, historically)",
        "",
        "**Sloan accruals ratio:**",
        "- > 0.10: high accruals, earnings quality concern",
        "- < 0.10: normal accruals",
    ]

    if report.notes:
        md_parts += ["", "## Notes", ""] + [f"- {n}" for n in report.notes]

    md = "\n".join(md_parts)

    if format == "markdown":
        Path(output_path).write_text(md)
        return output_path
    elif format == "pdf":
        return markdown_to_pdf(md, output_path=output_path,
                               title=f"Forensic report: {report.company}")
    else:
        raise ValueError(f"Unknown format: {format}")


def render_network_report(
    graph: NetworkGraph,
    *,
    output_path: str,
    format: str = "markdown",
    include_viz: bool = True,
) -> str:
    """Render a NetworkGraph discovery as Markdown or PDF.

    If include_viz=True and format="pdf", also generates a PNG visualization
    and embeds it.
    """
    md_parts = [
        f"# Network discovery: {graph.seed}",
        f"**Generated:** {graph.metadata.get('created', '?')}",
        f"**Nodes:** {len(graph.nodes)}  **Edges:** {len(graph.edges)}",
        f"**Sources succeeded:** {', '.join(graph.metadata.get('sources_succeeded', []))}",
        "",
    ]

    if include_viz and format == "pdf":
        from econscope.report.network_viz import render_network
        viz_path = output_path.replace(".pdf", "_viz.png")
        render_network(graph, output=viz_path)
        md_parts += [f"![Network visualization]({viz_path})", ""]

    md_parts += [
        "## Top connections by weight",
        "",
        "| Target | Weight | Sources |",
        "|--------|--------|---------|",
    ]
    for e in graph.top_by_weight(20):
        kinds = "+".join(e.kinds)
        md_parts.append(f"| {e.target[:60]} | {e.weight:.1f} | {kinds} |")

    md_parts += ["", "## Brokers (betweenness centrality)", ""]
    brokers = graph.brokers(top=10)
    if brokers:
        md_parts += ["| Node | Score |", "|------|-------|"]
        for node_id, score in brokers:
            md_parts.append(f"| {node_id[:60]} | {score:.3f} |")
    else:
        md_parts.append("(networkx not available or graph too small)")

    md = "\n".join(md_parts)

    if format == "markdown":
        Path(output_path).write_text(md)
        return output_path
    elif format == "pdf":
        return markdown_to_pdf(md, output_path=output_path,
                               title=f"Network discovery: {graph.seed}")
    else:
        raise ValueError(f"Unknown format: {format}")
