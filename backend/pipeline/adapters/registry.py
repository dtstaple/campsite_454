"""
Adapter registry.

Adapters self-register with the @register decorator, so wiring a new source into the CLI
means writing the adapter class and nothing else. The registry never needs editing, and
neither does the management command.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from pipeline.adapters.base import SourceAdapter

_REGISTRY: dict[str, type["SourceAdapter"]] = {}


class UnknownAdapterError(KeyError):
    """A source was requested that no adapter has registered for."""

    def __str__(self):
        # KeyError's default __str__ wraps the message in quotes; drop them so the
        # message reads cleanly when a management command prints it.
        return self.args[0] if self.args else ""


def register(cls: type["SourceAdapter"]) -> type["SourceAdapter"]:
    """Class decorator that adds an adapter to the registry under its `name`."""
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(f"{cls.__name__} must set a non-empty `name` to be registered")

    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"Cannot register {cls.__name__} as '{name}': already taken by {existing.__name__}"
        )

    _REGISTRY[name] = cls
    return cls


def get_adapter(name: str) -> type["SourceAdapter"]:
    """One adapter class by name, or UnknownAdapterError listing what is registered."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownAdapterError(f"Unknown source '{name}'. Available: {available}") from None


def list_adapters() -> list[str]:
    """Registered adapter names, sorted."""
    return sorted(_REGISTRY)


def unregister(name: str) -> None:
    """Remove an adapter. For tests that register a throwaway adapter."""
    _REGISTRY.pop(name, None)


def snapshot() -> dict[str, type["SourceAdapter"]]:
    """Shallow copy of the registry, so a test can restore it afterwards."""
    return dict(_REGISTRY)


def restore(saved: dict[str, type["SourceAdapter"]]) -> None:
    """Replace registry contents with a previous snapshot."""
    _REGISTRY.clear()
    _REGISTRY.update(saved)
