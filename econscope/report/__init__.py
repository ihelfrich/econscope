"""Report generation: charts, templates, render-to-PDF.

The `report` layer takes the structured outputs of `intel` and `analyze` and
turns them into deliverables: charts, executive summaries, full investigative
reports. It's the "translate research into reading" layer.

Submodules:
- `charts`   — Standard chart styles, palette, and one-line helpers
- `network_viz` — Render a NetworkGraph as a publication-quality PNG
- `render`   — Markdown to PDF via xelatex
"""

from econscope.report.charts import (
    PALETTE,
    set_style,
    timeline_chart,
    distribution_chart,
)
from econscope.report.network_viz import (
    render_network,
)
from econscope.report.render import (
    markdown_to_pdf,
    render_forensic_report,
    render_network_report,
)

__all__ = [
    "PALETTE",
    "set_style",
    "timeline_chart",
    "distribution_chart",
    "render_network",
    "markdown_to_pdf",
    "render_forensic_report",
    "render_network_report",
]
