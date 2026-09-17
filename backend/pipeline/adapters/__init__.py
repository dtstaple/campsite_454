"""
Source adapters.

Importing this package registers every shipped adapter (PipelineConfig.ready does it at
startup). Real adapters -- RIDB, OSM, NHD, PAD-US -- land in TM05-13; until then the
registry is intentionally empty, which is what proves the framework does not depend on
any particular source existing.

To add a source: create a module here, subclass SourceAdapter, decorate it with
@register, and import it below. No other file changes.
"""

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
