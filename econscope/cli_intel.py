"""ECONSCOPE CLI extensions: intel, analyze, report commands.

Exposes `register(app)`, called once by cli.py to attach all intel/analyze/report
commands onto the main typer app. The function-based registration avoids the
`__main__` vs imported-module identity trap that breaks decorator-based
registration when cli.py is run as a script.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer


def register(app: typer.Typer) -> None:
    """Attach all intel/analyze/report commands onto the given typer app."""

    # ════════════════════════════════════════════════════════════════════════
    # INTEL commands
    # ════════════════════════════════════════════════════════════════════════

    @app.command()
    def discover(
        entity: str = typer.Argument(..., help="Seed entity (person or company name)"),
        output: Optional[str] = typer.Option(None, "--out", "-o", help="Save graph JSON to this path"),
        skip_wiki: bool = typer.Option(False, "--skip-wiki", help="Skip Wikidata expansion"),
        skip_gdelt: bool = typer.Option(False, "--skip-gdelt", help="Skip GDELT news lookup"),
        edgar_limit: int = typer.Option(200, "--edgar-limit", help="Max EDGAR FTS results"),
        threshold: int = typer.Option(2, "--threshold", help="Min co-mention count to include"),
    ):
        """Run multi-source connection discovery from a seed entity."""
        from econscope.intel.network import discover as do_discover, summarize

        typer.echo(f"Discovering connections for '{entity}'...", err=True)
        graph = do_discover(
            entity,
            edgar_limit=edgar_limit,
            skip_wiki=skip_wiki,
            skip_gdelt=skip_gdelt,
            co_mention_threshold=threshold,
        )
        typer.echo(summarize(graph))
        if output:
            Path(output).write_text(graph.to_json())
            typer.echo(f"\nGraph saved to {output}", err=True)

    @app.command()
    def forensic(
        cik: int = typer.Argument(..., help="Company CIK number"),
        output: Optional[str] = typer.Option(None, "--out", "-o", help="Save report JSON"),
        pdf: Optional[str] = typer.Option(None, "--pdf", help="Render as PDF to this path"),
    ):
        """Compute Beneish/Altman/Sloan forensic scores from SEC EDGAR XBRL."""
        from econscope.intel.forensic import forensic_report, summarize_report

        typer.echo(f"Pulling XBRL facts for CIK {cik}...", err=True)
        report = forensic_report(cik)
        typer.echo(summarize_report(report))
        if output:
            Path(output).write_text(report.to_json())
            typer.echo(f"\nReport saved to {output}", err=True)
        if pdf:
            from econscope.report.render import render_forensic_report
            render_forensic_report(report, output_path=pdf, format="pdf")
            typer.echo(f"PDF saved to {pdf}", err=True)

    @app.command()
    def proxy(
        cik: int = typer.Argument(..., help="Company CIK"),
        accession: str = typer.Argument(..., help="Filing accession"),
        output: Optional[str] = typer.Option(None, "--out", "-o", help="Save extraction JSON"),
    ):
        """Parse a proxy statement (DEFM14A / DEF 14A / PRER14A)."""
        from econscope.intel.proxies import parse_proxy, summarize_extraction

        typer.echo(f"Parsing proxy {accession} for CIK {cik}...", err=True)
        try:
            extraction = parse_proxy(cik, accession)
        except Exception as e:
            typer.echo(f"ERROR: {e}", err=True)
            raise typer.Exit(1)
        typer.echo(summarize_extraction(extraction))
        if output:
            Path(output).write_text(extraction.to_json())
            typer.echo(f"\nExtraction saved to {output}", err=True)

    # ════════════════════════════════════════════════════════════════════════
    # ANALYZE commands
    # ════════════════════════════════════════════════════════════════════════

    @app.command(name="monte-carlo")
    def monte_carlo_cmd(
        debt: float = typer.Option(..., "--debt", help="Debt amount (USD)"),
        base_oi: float = typer.Option(..., "--base-oi", help="Base operating income (USD)"),
        rate_low: float = typer.Option(0.06, "--rate-low", help="Low refinancing rate"),
        rate_high: float = typer.Option(0.11, "--rate-high", help="High refinancing rate"),
        oi_std: float = typer.Option(..., "--oi-std", help="Std dev of operating income"),
        draws: int = typer.Option(10_000, "--draws", help="Number of MC draws"),
        threshold: float = typer.Option(1.0, "--threshold", help="Distress coverage threshold"),
        output_png: Optional[str] = typer.Option(None, "--png", help="Save histogram PNG"),
    ):
        """Run a Monte Carlo refinancing distress simulation."""
        from econscope.analyze import refinancing_simulation
        from econscope.report.charts import distribution_chart

        result = refinancing_simulation(
            debt_amount=debt,
            base_operating_income=base_oi,
            rate_range=(rate_low, rate_high),
            oi_std=oi_std,
            n_draws=draws,
            distress_threshold=threshold,
        )
        typer.echo(result.summary())
        if output_png:
            distribution_chart(
                result.coverage_samples,
                bins=80,
                title="Refinancing distress simulation",
                xlabel="Interest coverage ratio",
                distress_threshold=threshold,
                output=output_png,
            )
            typer.echo(f"\nHistogram saved to {output_png}", err=True)

    # ════════════════════════════════════════════════════════════════════════
    # REPORT commands
    # ════════════════════════════════════════════════════════════════════════

    @app.command()
    def viz(
        graph_file: str = typer.Argument(..., help="Path to a NetworkGraph JSON file"),
        output: str = typer.Option("network.png", "--out", "-o", help="Output PNG path"),
        layout: str = typer.Option("radial", "--layout", help="radial or force"),
        max_nodes: int = typer.Option(30, "--max-nodes", help="Max nodes to render"),
    ):
        """Render a NetworkGraph (from `econscope discover`) as PNG."""
        from econscope.intel.network import NetworkGraph
        from econscope.report.network_viz import render_network

        graph = NetworkGraph.from_json(Path(graph_file).read_text())
        out = render_network(graph, output=output, layout=layout, max_nodes=max_nodes)
        typer.echo(f"Visualization saved to {out}")

    @app.command()
    def cache(
        action: str = typer.Argument("size", help="size or clear"),
    ):
        """Inspect or clear the intel HTTP cache."""
        from econscope.intel.http import cache_size, cache_clear

        if action == "size":
            info = cache_size()
            mb = info["bytes"] / (1024 * 1024)
            typer.echo(f"Cache: {info['entries']} entries, {mb:.1f} MB at {info['path']}")
        elif action == "clear":
            n = cache_clear()
            typer.echo(f"Cleared {n} cached entries.")
        else:
            typer.echo(f"Unknown action: {action}. Use 'size' or 'clear'.")
            raise typer.Exit(1)

    @app.command()
    def chain(
        entity: str = typer.Argument(..., help="Seed entity"),
        out_dir: str = typer.Option("./chain_out", "--out", "-o", help="Output directory"),
        skip_wiki: bool = typer.Option(True, "--skip-wiki", help="Skip Wikidata (often rate-limited)"),
        skip_gdelt: bool = typer.Option(True, "--skip-gdelt", help="Skip GDELT"),
        threshold: int = typer.Option(3, "--threshold", help="Min co-mention count"),
        max_companies: int = typer.Option(15, "--max-companies", help="Max companies to score"),
    ):
        """Pipeline: discover network → run forensic on every discovered company.

        Builds the connection graph, extracts the CIKs of co-mentioned entities,
        runs Beneish/Altman/Sloan on each, and writes a synthesis report combining
        the network + forensic findings. This is the canonical multi-step
        investigation workflow.

        Example:
          econscope chain "Ron Burkle" --out burkle_chain
        """
        import re
        from econscope.intel.network import discover as do_discover, summarize
        from econscope.intel.forensic import forensic_report
        from econscope.report.network_viz import render_network

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        # ── Step 1: discover ────────────────────────────────────────
        typer.echo(f"[1/3] Discovering connections for '{entity}'...", err=True)
        graph = do_discover(
            entity,
            skip_wiki=skip_wiki,
            skip_gdelt=skip_gdelt,
            co_mention_threshold=threshold,
        )
        (out / "graph.json").write_text(graph.to_json())
        typer.echo(f"      {len(graph.nodes)} nodes, {len(graph.edges)} edges", err=True)

        # ── Step 2: render visualization ────────────────────────────
        typer.echo("[2/3] Rendering network visualization...", err=True)
        render_network(graph, output=str(out / "network.png"))

        # ── Step 3: forensic on each CIK ────────────────────────────
        cik_re = re.compile(r"CIK\s+0*(\d+)")
        seen_ciks: set[int] = set()
        for node in graph.nodes:
            m = cik_re.search(node.id)
            if m:
                seen_ciks.add(int(m.group(1)))

        typer.echo(
            f"[3/3] Running forensic on {min(len(seen_ciks), max_companies)} CIKs...",
            err=True,
        )
        forensic_results = []
        for cik in sorted(seen_ciks)[:max_companies]:
            try:
                fr = forensic_report(cik)
                forensic_results.append(fr)
                latest = fr.years[-1] if fr.years else None
                if latest:
                    flags = ",".join(latest.flags) if latest.flags else "—"
                    typer.echo(
                        f"      CIK {cik:>10}  {fr.company[:35]:<35}  "
                        f"Z={latest.altman_z or 'n/a':>6}  flags={flags}",
                        err=True,
                    )
            except Exception as e:
                typer.echo(f"      CIK {cik}: {e}", err=True)

        # ── Synthesis report ────────────────────────────────────────
        synthesis = [
            f"# Chain investigation: {entity}",
            f"",
            f"**Generated:** {graph.metadata.get('created', '?')}",
            f"**Network:** {len(graph.nodes)} nodes, {len(graph.edges)} edges",
            f"**Forensic:** {len(forensic_results)} companies analyzed",
            f"",
            f"![Network visualization](network.png)",
            f"",
            f"## Top connections",
            f"",
            f"| Entity | Weight | Source |",
            f"|--------|--------|--------|",
        ]
        for e in graph.top_by_weight(15):
            synthesis.append(f"| {e.target[:55]} | {e.weight:.1f} | {'+'.join(e.kinds)} |")

        synthesis += [
            f"",
            f"## Forensic snapshot (latest year per company)",
            f"",
            f"| CIK | Company | Beneish M | Altman Z | Sloan | Flags |",
            f"|-----|---------|-----------|----------|-------|-------|",
        ]
        for fr in forensic_results:
            if not fr.years:
                continue
            y = fr.years[-1]
            m = f"{y.beneish_m:.2f}" if y.beneish_m is not None else "n/a"
            z = f"{y.altman_z:.2f}" if y.altman_z is not None else "n/a"
            s = f"{y.sloan_accruals:.3f}" if y.sloan_accruals is not None else "n/a"
            flags = ", ".join(y.flags) if y.flags else "—"
            synthesis.append(
                f"| {fr.cik} | {fr.company[:35]} | {m} | {z} | {s} | {flags} |"
            )

        (out / "synthesis.md").write_text("\n".join(synthesis))
        typer.echo(
            f"\nOutput written to {out}/\n  - graph.json\n  - network.png\n  - synthesis.md",
            err=True,
        )
