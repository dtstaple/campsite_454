"""
Source adapters.

Importing this package registers every shipped adapter (PipelineConfig.ready does it at
startup).

All four TM05-13 sources are shipped: PAD-US (public land), OSM trails, USGS NHD water
(flowlines and waterbodies), and RIDB campsites.

To add a source: create a module here, subclass SourceAdapter, decorate it with
@register, and import it below. No other file changes.
"""

# Importing each adapter module is what triggers its @register decorator.
from pipeline.adapters import nhd, osm_trails, padus, ridb  # noqa: E402,F401  (order deliberate)
from pipeline.adapters.base import (
    AdapterConfigurationError,
    AdapterError,
    GeometryTypeMismatch,
    SourceAdapter,
)
from pipeline.adapters.registry import (
    UnknownAdapterError,
    get_adapter,
    list_adapters,
    register,
)

__all__ = [
    "AdapterConfigurationError",
    "AdapterError",
    "GeometryTypeMismatch",
    "SourceAdapter",
    "UnknownAdapterError",
    "get_adapter",
    "list_adapters",
    "register",
]
