"""
The terrain tool registry (TM05-141): terrain/tools.yml, loaded and checked.

Loading validates everything that can be checked without running a tool. That covers
grid references, step references, sample methods and mapper names, and that zone classes
are ordered. A typo in the config therefore fails at load, with the tool's name, rather
than an hour into a run.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).with_name("tools.yml")

#: How a fact is read from a tool's raster around a site (terrain/mappers.py).
SAMPLE_METHODS = ("median", "max", "min", "circular_mean")
#: Mappers that compute a fact from something other than one raster sample.
MAPPERS = ("viewshed",)

_REFERENCE = re.compile(r"\{(\w+)\}")


class RegistryError(ValueError):
    """tools.yml is malformed."""


@dataclass(frozen=True)
class Grid:
    name: str
    resolution_m: float
    #: Tile core size in cells; None is the whole region in one piece.
    tile_cells: int | None = None
    overlap_m: float = 0.0
    #: Process only tiles whose core holds a campsite (grids that make no zones).
    sites_only: bool = False


@dataclass(frozen=True)
class Step:
    id: str
    tool: str
    #: GeoLibre arguments. A "{name}" value is `{dem}` or an earlier step's output.
    args: dict[str, Any]

    def references(self) -> list[str]:
        return [m for value in self.args.values() for m in _REFERENCE.findall(str(value))]


@dataclass(frozen=True)
class FactSpec:
    name: str
    sample: str | None = None
    radius_m: float = 0.0
    mapper: str | None = None


@dataclass(frozen=True)
class ZoneClass:
    name: str
    min: float


@dataclass(frozen=True)
class ZoneSpec:
    layer: str
    #: Ascending by `min`: a cell takes the highest class whose minimum it reaches.
    classes: tuple[ZoneClass, ...]
    min_area_m2: float
    simplify_m: float


@dataclass(frozen=True)
class Tool:
    id: str
    grid: Grid
    steps: tuple[Step, ...] = ()
    facts: tuple[FactSpec, ...] = ()
    zones: ZoneSpec | None = None
    #: Set for a tool run once per campsite on a window, not over tiles.
    per_site: dict[str, float] | None = None

    @property
    def geolibre_tools(self) -> list[str]:
        return [step.tool for step in self.steps] + (["viewshed"] if self.per_site else [])


@dataclass(frozen=True)
class Registry:
    runtime: dict[str, str]
    dem: dict[str, Any]
    grids: dict[str, Grid]
    tools: dict[str, Tool]
    classify: dict[str, Any]
    #: The parsed config, for provenance.
    raw: dict[str, Any] = field(repr=False)

    @property
    def digest(self) -> str:
        """A short hash of what tile results depend on. Tile results are reused only under
        the same one. `classify` is left out: classes are rebuilt from stored values on
        every run, so changing a threshold doesn't recompute any tile."""
        tiles = {key: value for key, value in self.raw.items() if key != "classify"}
        canonical = json.dumps(tiles, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _need(body: dict, key: str, where: str):
    if key not in body:
        raise RegistryError(f"{where}: missing '{key}'")
    return body[key]


def _grid(name: str, body: dict) -> Grid:
    resolution = float(_need(body, "resolution_m", f"grid {name}"))
    if resolution <= 0:
        raise RegistryError(f"grid {name}: resolution_m must be positive")
    cells = body.get("tile_cells")
    if cells is not None and int(cells) < 1:
        raise RegistryError(f"grid {name}: tile_cells must be at least 1")
    return Grid(
        name=name,
        resolution_m=resolution,
        tile_cells=int(cells) if cells is not None else None,
        overlap_m=float(body.get("overlap_m", 0.0)),
        sites_only=bool(body.get("sites_only", False)),
    )


def _facts(tool: str, body: dict) -> tuple[FactSpec, ...]:
    facts = []
    for name, spec in (body or {}).items():
        where = f"tool {tool}, fact {name}"
        sample, mapper = spec.get("sample"), spec.get("mapper")
        if (sample is None) == (mapper is None):
            raise RegistryError(f"{where}: give exactly one of 'sample' or 'mapper'")
        if sample is not None and sample not in SAMPLE_METHODS:
            raise RegistryError(f"{where}: unknown sample '{sample}', use {SAMPLE_METHODS}")
        if mapper is not None and mapper not in MAPPERS:
            raise RegistryError(f"{where}: unknown mapper '{mapper}', use {MAPPERS}")
        facts.append(FactSpec(name, sample, float(spec.get("radius_m", 0.0)), mapper))
    return tuple(facts)


def _zones(tool: str, body: dict | None) -> ZoneSpec | None:
    if body is None:
        return None
    where = f"tool {tool}, zones"
    classes = tuple(
        ZoneClass(str(_need(c, "class", where)), float(_need(c, "min", where)))
        for c in _need(body, "classes", where)
    )
    if not classes:
        raise RegistryError(f"{where}: needs at least one class")
    minimums = [c.min for c in classes]
    if minimums != sorted(minimums) or len(set(minimums)) != len(minimums):
        raise RegistryError(f"{where}: classes must have strictly increasing 'min'")
    return ZoneSpec(
        layer=str(_need(body, "layer", where)),
        classes=classes,
        min_area_m2=float(body.get("min_area_m2", 0.0)),
        simplify_m=float(body.get("simplify_m", 0.0)),
    )


def _tool(name: str, body: dict, grids: dict[str, Grid]) -> Tool:
    grid_name = _need(body, "grid", f"tool {name}")
    if grid_name not in grids:
        raise RegistryError(f"tool {name}: unknown grid '{grid_name}', use {list(grids)}")
    steps: list[Step] = []
    for raw in body.get("steps") or []:
        step = Step(
            str(_need(raw, "id", f"tool {name}")),
            str(_need(raw, "tool", f"tool {name}")),
            dict(raw.get("args") or {}),
        )
        known = {"dem"} | {s.id for s in steps}
        for ref in step.references():
            if ref not in known:
                raise RegistryError(
                    f"tool {name}, step {step.id}: '{{{ref}}}' is not the dem or an earlier step"
                )
        steps.append(step)
    per_site = body.get("per_site")
    if not steps and not per_site:
        raise RegistryError(f"tool {name}: needs 'steps' or 'per_site'")
    tool = Tool(
        id=name,
        grid=grids[grid_name],
        steps=tuple(steps),
        facts=_facts(name, body.get("facts")),
        zones=_zones(name, body.get("zones")),
        per_site={k: float(v) for k, v in per_site.items()} if per_site else None,
    )
    if not tool.facts and tool.zones is None:
        raise RegistryError(f"tool {name}: produces nothing (no 'facts' or 'zones')")
    return tool


def load(path: Path | str | None = None) -> Registry:
    path = Path(path) if path else DEFAULT_PATH
    raw = yaml.safe_load(path.read_text()) or {}
    grids = {name: _grid(name, body) for name, body in _need(raw, "grids", str(path)).items()}
    tools = {
        name: _tool(name, body, grids) for name, body in _need(raw, "tools", str(path)).items()
    }
    names = [fact.name for tool in tools.values() for fact in tool.facts]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise RegistryError(f"{path}: facts named by more than one tool: {duplicated}")
    layers = [tool.zones.layer for tool in tools.values() if tool.zones]
    if len(layers) != len(set(layers)):
        raise RegistryError(f"{path}: two tools write the same zone layer")
    return Registry(
        runtime=dict(_need(raw, "runtime", str(path))),
        dem=dict(_need(raw, "dem", str(path))),
        grids=grids,
        tools=tools,
        classify=dict(raw.get("classify") or {}),
        raw=raw,
    )
