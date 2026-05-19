"""ECONSCOPE cross-source query engine."""

from econscope.engine.core import (
    get_adapter,
    multi_pull,
    correlate,
    entity_search,
    warehouse_join,
    summary_stats,
    SeriesSpec,
    PanelResult,
    ADAPTER_REGISTRY,
)

__all__ = [
    "get_adapter",
    "multi_pull",
    "correlate",
    "entity_search",
    "warehouse_join",
    "summary_stats",
    "SeriesSpec",
    "PanelResult",
    "ADAPTER_REGISTRY",
]
