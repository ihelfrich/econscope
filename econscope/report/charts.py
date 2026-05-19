"""Standard chart styling for ECONSCOPE reports.

A small set of conventions that make every chart from ECONSCOPE look like it
came from the same hand. Palette, font, axis style, caption placement.

The point of having a chart style module is consistency. Without it, every
analysis produces visually-distinct charts and the report looks like a
collage. With it, all the figures in a deliverable feel like they belong
together.
"""

from __future__ import annotations

from typing import Optional


# ── Palette ──────────────────────────────────────────────────────────────────
# The colors we've been using across the Soho House work. Each has a
# semantic role to make charts read more naturally.

PALETTE = {
    "primary":     "#2E86AB",   # Section headers, primary series
    "accent_red":  "#E05263",   # Risk, decline, distress
    "accent_gold": "#F5A623",   # Pivot, mixed, warning
    "accent_green":"#4CAF50",   # Positive, growth, opportunity
    "accent_blue": "#3F88C5",   # Secondary series
    "accent_purple":"#7B68AE",  # Strategic / interpretive
    "gray":        "#888888",   # Auxiliary text
    "dark":        "#2D2D2D",   # Body text, axis labels
    "light_bg":    "#F0F4F7",   # Card backgrounds
    "off_white":   "#FAFAFA",   # Figure background
}


def set_style(*, font: str = "Helvetica Neue") -> None:
    """Apply ECONSCOPE chart style to matplotlib's rcParams.

    Call once at the start of any plotting script. Idempotent.
    """
    try:
        import matplotlib
        import matplotlib.pyplot as plt
    except ImportError:
        return

    matplotlib.rcParams.update({
        "font.family": font,
        "axes.edgecolor": PALETTE["gray"],
        "axes.linewidth": 0.5,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelcolor": PALETTE["dark"],
        "axes.labelsize": 9,
        "xtick.color": PALETTE["gray"],
        "ytick.color": PALETTE["gray"],
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": PALETTE["off_white"],
        "axes.facecolor": PALETTE["off_white"],
        "axes.grid": True,
        "grid.color": PALETTE["light_bg"],
        "grid.linewidth": 0.5,
        "legend.frameon": False,
        "legend.fontsize": 8,
    })


# ── One-line helpers ─────────────────────────────────────────────────────────

def timeline_chart(
    x: list,
    y: list,
    *,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    color: str = None,
    output: Optional[str] = None,
    fig_size: tuple[float, float] = (10, 5),
    annotations: Optional[list[tuple]] = None,
):
    """Draw a single time-series line with the ECONSCOPE style.

    Parameters
    ----------
    x, y : sequence
        X and Y values.
    title, xlabel, ylabel : str
    color : str, optional
        Hex color; defaults to primary.
    output : str, optional
        Path to save PNG. If None, returns the figure object.
    fig_size : (w, h) tuple
    annotations : list of (x_position, y_position, text, color) tuples

    Returns the matplotlib figure.
    """
    import matplotlib.pyplot as plt
    set_style()

    fig, ax = plt.subplots(figsize=fig_size)
    ax.plot(x, y, color=color or PALETTE["primary"], linewidth=2)
    if title:
        ax.set_title(title, loc="left", color=PALETTE["dark"])
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    if annotations:
        for ax_x, ax_y, txt, col in annotations:
            ax.annotate(
                txt, xy=(ax_x, ax_y), fontsize=8, color=col or PALETTE["dark"],
                ha="center",
            )

    plt.tight_layout()
    if output:
        plt.savefig(output, dpi=200, bbox_inches="tight", facecolor=PALETTE["off_white"])
        plt.close()
    return fig


def distribution_chart(
    samples: list[float],
    *,
    bins: int = 50,
    title: str = "",
    xlabel: str = "",
    distress_threshold: Optional[float] = None,
    output: Optional[str] = None,
    fig_size: tuple[float, float] = (10, 5),
):
    """Histogram of a sample distribution, with optional distress threshold shading.

    Used for Monte Carlo coverage-ratio outputs.
    """
    import matplotlib.pyplot as plt
    set_style()

    fig, ax = plt.subplots(figsize=fig_size)
    counts, edges, _ = ax.hist(
        samples, bins=bins, color=PALETTE["primary"], alpha=0.7, edgecolor="white"
    )

    if distress_threshold is not None:
        ax.axvline(distress_threshold, color=PALETTE["accent_red"], linewidth=1.5, linestyle="--")
        # Shade distress region
        ymax = counts.max()
        ax.fill_betweenx(
            [0, ymax],
            min(samples) if min(samples) < distress_threshold else distress_threshold,
            distress_threshold,
            alpha=0.08, color=PALETTE["accent_red"],
        )
        # Annotate
        prob = sum(1 for s in samples if s < distress_threshold) / len(samples)
        ax.text(
            distress_threshold, ymax * 0.95,
            f"  Distress\n  {prob:.1%}", fontsize=9, fontweight="bold",
            color=PALETTE["accent_red"], ha="left", va="top",
        )

    if title:
        ax.set_title(title, loc="left", color=PALETTE["dark"])
    if xlabel:
        ax.set_xlabel(xlabel)
    ax.set_ylabel("Frequency")

    plt.tight_layout()
    if output:
        plt.savefig(output, dpi=200, bbox_inches="tight", facecolor=PALETTE["off_white"])
        plt.close()
    return fig
