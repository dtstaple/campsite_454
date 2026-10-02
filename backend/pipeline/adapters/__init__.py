"""
Source adapters.

Importing this package registers every shipped adapter (PipelineConfig.ready does it at
startup).

Shipped: PAD-US (public land), OSM trails, OSM hiking routes, USGS NHD water (flowlines
and waterbodies), RIDB campsites, and OSM campsites. Campsites come from two sources because RIDB is
federal-only and the Adirondacks are state land -- see osm_campsites.

To add a source: create a module here, subclass SourceAdapter, decorate it with
@register, and import it below. No other file changes.
"""

# Importing each adapter module is what triggers its @register decorator.
from pipeline.adapters import (  # noqa: E402,F401  (order deliberate)
    nhd,
    osm_campsites,
    osm_routes,
    osm_trails,
    padus,
    ridb,
)
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
