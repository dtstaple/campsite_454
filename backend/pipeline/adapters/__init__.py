"""
Source adapters.

Importing this package registers every shipped adapter (PipelineConfig.ready does it at
startup).

Shipped so far: PAD-US (public land and legal access). OSM trails, USGS NHD water, and
Recreation.gov campsites are the remaining TM05-13 work.

To add a source: create a module here, subclass SourceAdapter, decorate it with
@register, and import it below. No other file changes.
"""

# Importing each adapter module is what triggers its @register decorator.
from pipeline.adapters import padus  # noqa: E402,F401  (import order is deliberate)
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
