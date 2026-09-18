"""
Loader for the region config.

Regions come from regions.yml so that adding an area of interest is a config change
rather than a code change -- the rule in CLAUDE.md section 7 that areas of interest never
come from hardcoded bounding boxes.

Results are cached per file path. Tests that need a different config pass an explicit
path, which caches separately and leaves the shipped config untouched.
"""

from functools import cache
from pathlib import Path

import yaml

from pipeline.aoi import AreaOfInterest

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "regions.yml"


class RegionConfigError(Exception):
    """The region config is missing, unreadable, or structurally wrong."""


class UnknownRegionError(RegionConfigError):
    """A region was requested that the config does not define."""


def _parse(raw: object, path: Path) -> dict[str, AreaOfInterest]:
    if not isinstance(raw, dict) or "regions" not in raw:
        raise RegionConfigError(f"{path}: expected a top-level 'regions:' mapping")

    entries = raw["regions"]
    if not isinstance(entries, dict) or not entries:
        raise RegionConfigError(f"{path}: 'regions' must be a non-empty mapping")

    areas: dict[str, AreaOfInterest] = {}
    for name, body in entries.items():
        if not isinstance(body, dict):
            raise RegionConfigError(f"{path}: region '{name}' must be a mapping")
        if "bbox" not in body:
            raise RegionConfigError(f"{path}: region '{name}' is missing 'bbox'")

        areas[name] = AreaOfInterest(
            name=name,
            label=body.get("label", name),
            bbox=tuple(body["bbox"]),
            states=tuple(body.get("states", ())),
            notes=(body.get("notes") or "").strip(),
        )
    return areas


@cache
def load_regions(path: Path | str | None = None) -> dict[str, AreaOfInterest]:
    """Every configured region, keyed by name. Cached per path."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = yaml.safe_load(config_path.read_text())
    except FileNotFoundError as exc:
        raise RegionConfigError(f"No region config at {config_path}") from exc
    except yaml.YAMLError as exc:
        raise RegionConfigError(f"{config_path} is not valid YAML: {exc}") from exc

    return _parse(raw, config_path)


def get_region(name: str, path: Path | str | None = None) -> AreaOfInterest:
    """One region by name, or UnknownRegionError listing what is available."""
    areas = load_regions(path)
    try:
        return areas[name]
    except KeyError:
        raise UnknownRegionError(
            f"Unknown region '{name}'. Available: {', '.join(sorted(areas))}"
        ) from None


def list_regions(path: Path | str | None = None) -> list[str]:
    """Configured region names, sorted."""
    return sorted(load_regions(path))
