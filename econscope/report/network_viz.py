"""Render a NetworkGraph as a publication-quality PNG.

The standalone deepwire tool emits JSON. To convert that into a visualization
required a separate matplotlib script every time. This module is that script,
packaged: any NetworkGraph can be rendered with one call.

Two layouts are supported:
- "radial": seed at center, neighbors on a circle, sized by edge weight
- "force":  networkx spring layout (more organic for larger graphs)

The visual style matches the rest of ECONSCOPE's chart palette.
"""

from __future__ import annotations

import math
from typing import Optional

from econscope.intel.network import NetworkGraph
from econscope.report.charts import PALETTE, set_style


def render_network(
    graph: NetworkGraph,
    *,
    output: str,
    layout: str = "radial",
    fig_size: tuple[float, float] = (12, 10),
    title: Optional[str] = None,
    max_nodes: int = 30,
) -> str:
    """Render a NetworkGraph to PNG.

    Parameters
    ----------
    graph : NetworkGraph
        The graph to render.
    output : str
        File path for the PNG output.
    layout : str
        "radial" or "force".
    fig_size : tuple
        Figure size in inches.
    title : str, optional
        Override the default title.
    max_nodes : int
        If the graph has more nodes than this, keep only the top-weighted edges.

    Returns the path to the saved PNG.
    """
    import matplotlib.pyplot as plt
    set_style()

    # Filter to top edges if too many nodes
    edges = sorted(graph.edges, key=lambda e: e.weight, reverse=True)
    if len(graph.nodes) > max_nodes:
        keep_targets = {e.target for e in edges[:max_nodes - 1]}
        keep_targets.add(graph.seed)
        nodes = [n for n in graph.nodes if n.id in keep_targets]
        edges = [e for e in edges if e.source in keep_targets and e.target in keep_targets]
    else:
        nodes = graph.nodes

    fig, ax = plt.subplots(figsize=fig_size)
    ax.set_facecolor(PALETTE["off_white"])

    # Color by node kind
    color_map = {
        "seed":        PALETTE["accent_purple"],
        "sec_entity":  PALETTE["primary"],
        "holder":      PALETTE["accent_blue"],
        "wikidata":    PALETTE["accent_gold"],
        "news_entity": PALETTE["accent_green"],
    }

    if layout == "radial":
        positions = _radial_layout(nodes, seed=graph.seed)
    else:
        positions = _force_layout(nodes, edges, seed=graph.seed)

    # Draw edges
    for e in edges:
        if e.source not in positions or e.target not in positions:
            continue
        x1, y1 = positions[e.source]
        x2, y2 = positions[e.target]
        lw = min(0.3 + e.weight / 5, 4.0)
        ax.plot(
            [x1, x2], [y1, y2],
            color=PALETTE["gray"], alpha=0.25, linewidth=lw, zorder=1,
        )

    # Draw nodes
    for n in nodes:
        if n.id not in positions:
            continue
        x, y = positions[n.id]
        color = color_map.get(n.kind, PALETTE["gray"])

        # Size by sum of weights of incident edges, capped
        total_weight = sum(e.weight for e in edges if e.source == n.id or e.target == n.id)
        node_size = min(300 + total_weight * 40, 2500)

        if n.kind == "seed":
            node_size = 2500

        ax.scatter(
            [x], [y], s=node_size, color=color, alpha=0.25 if n.kind != "seed" else 0.85,
            edgecolors=color, linewidths=2, zorder=3,
        )

        # Label
        label = n.label[:35]
        if n.kind == "seed":
            ax.text(x, y, label.upper(), ha="center", va="center", fontsize=10,
                    fontweight="bold", color="white", zorder=5)
        else:
            ax.text(x, y, label, ha="center", va="center", fontsize=7,
                    color=PALETTE["dark"], zorder=4, linespacing=1.3)

    # Legend
    legend_kinds = sorted({n.kind for n in nodes if n.kind != "seed"})
    for i, kind in enumerate(legend_kinds):
        ax.scatter([], [], s=120, color=color_map.get(kind, PALETTE["gray"]),
                   alpha=0.4, label=kind.replace("_", " ").title())
    if legend_kinds:
        ax.legend(loc="upper left", fontsize=8)

    # Title
    title = title or f"Connection network: {graph.seed}"
    ax.text(
        0.02, 0.98, title, transform=ax.transAxes,
        fontsize=14, fontweight="bold", color=PALETTE["dark"],
        ha="left", va="top",
    )
    if graph.metadata.get("sources_succeeded"):
        subtitle = f"Sources: {', '.join(graph.metadata['sources_succeeded'])}  |  "
        subtitle += f"{len(nodes)} nodes, {len(edges)} edges"
        ax.text(
            0.02, 0.94, subtitle, transform=ax.transAxes,
            fontsize=8, color=PALETTE["gray"], ha="left", va="top", style="italic",
        )

    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_aspect("equal")

    plt.tight_layout()
    plt.savefig(output, dpi=200, bbox_inches="tight", facecolor=PALETTE["off_white"])
    plt.close()
    return output


def _radial_layout(nodes, *, seed: str) -> dict[str, tuple[float, float]]:
    """Place the seed at center, all others on a circle."""
    positions = {seed: (0.0, 0.0)}
    others = [n for n in nodes if n.id != seed]
    n = len(others)
    if n == 0:
        return positions
    R = 4.5
    for i, node in enumerate(others):
        angle = 2 * math.pi * i / n
        positions[node.id] = (R * math.cos(angle), R * math.sin(angle))
    return positions


def _force_layout(nodes, edges, *, seed: str) -> dict[str, tuple[float, float]]:
    """networkx spring layout. Falls back to radial if networkx isn't available."""
    try:
        import networkx as nx
    except ImportError:
        return _radial_layout(nodes, seed=seed)

    g = nx.Graph()
    for n in nodes:
        g.add_node(n.id)
    for e in edges:
        g.add_edge(e.source, e.target, weight=max(e.weight, 0.1))
    pos = nx.spring_layout(g, seed=42, weight="weight", k=1.5, iterations=80)
    # Scale to a comparable range
    return {nid: (5 * p[0], 5 * p[1]) for nid, p in pos.items()}
