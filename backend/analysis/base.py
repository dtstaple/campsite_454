"""
The Analysis contract (TM05-44): compute an answer on demand for a geometry and a time
window, cache the answer with a time-to-live, and record how it was produced.

It sits beside the ingestion framework (pipeline.adapters.base.SourceAdapter) and is its
counterpart for data that is too big or too live to persist wholesale:

    SourceAdapter: fetch(aoi) -> normalize(raw) -> load(records)    persist the data
    Analysis:      run(geom, window, params) -> compute() -> cache  persist the answer

A subclass declares four things and writes one method:

    class Slope(Analysis):
        name = "slope"
        version = "1"
        ttl = timedelta(days=365)        # terrain does not change
        grid_degrees = None              # exact geometry

        def compute(self, geom, window, params) -> Computed:
            ...                          # read pixels, return the answer + provenance

Everything else -- the cache key, the hit/miss decision, expiry, storing provenance -- is
here, once.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.gis.geos import GEOSGeometry, Point, WKTWriter
from django.utils import timezone

from analysis.models import AnalysisResult


@dataclass(frozen=True)
class Window:
    """A half-open time window [start, end). Both timezone-aware."""

    start: datetime
    end: datetime

    def as_key(self) -> list[str]:
        return [self.start.isoformat(), self.end.isoformat()]


@dataclass(frozen=True)
class Computed:
    """What compute() returns: the answer, and how it was obtained."""

    value: dict
    provenance: dict


@dataclass(frozen=True)
class Outcome:
    """What run() returns."""

    value: dict
    provenance: dict
    cached: bool
    key: str
    computed_at: datetime
    expires_at: datetime


class AnalysisError(Exception):
    """An analysis could not be computed (source unreachable, bad response)."""


def quantize(geom: GEOSGeometry, grid_degrees: float | None) -> GEOSGeometry:
    """Snap a point to the centre of a grid cell so nearby requests share a cache entry.

    Only points are snapped. Lines and polygons are keyed exactly (rounded to 6 places,
    ~0.1 m), because snapping a route or a parcel would change what is being analysed.
    """
    if not grid_degrees or not isinstance(geom, Point):
        return geom
    x, y = (round((v // grid_degrees) * grid_degrees + grid_degrees / 2, 6) for v in geom)
    return Point(x, y, srid=4326)


def canonical_geom(geom: GEOSGeometry) -> GEOSGeometry:
    """The geometry as it is keyed and stored: EPSG:4326, coordinates at 6 decimal places
    (~0.1 m), so float noise in a request cannot split one answer into two entries."""
    geom = geom.clone()
    if geom.srid is None:
        geom.srid = 4326
    elif geom.srid != 4326:
        geom.transform(4326)
    return GEOSGeometry(WKTWriter(precision=6).write(geom).decode(), srid=4326)


def cache_key(name: str, version: str, geom: GEOSGeometry, window: Window | None, params: dict):
    """The documented cache key: sha256 over a canonical JSON of everything that changes
    the answer -- analysis name and version, geometry (WKT, 6 decimal places), time
    window, and parameters (sorted). Any difference in any part is a different entry.
    `geom` should already be canonical_geom()."""
    payload = {
        "analysis": name,
        "version": version,
        "geom": geom.wkt,
        "window": window.as_key() if window else None,
        "params": params,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Analysis(ABC):
    #: Stable identifier, stored with every result.
    name: str = ""
    #: Bump to invalidate every cached result of this analysis.
    version: str = "1"
    #: How long an answer stays valid. Documented per analysis in docs/architecture.md.
    ttl: timedelta = timedelta(hours=1)
    #: Snap points to this grid (degrees) before keying; None keys the exact geometry.
    grid_degrees: float | None = None

    @abstractmethod
    def compute(self, geom: GEOSGeometry, window: Window | None, params: dict) -> Computed:
        """Produce the answer for this geometry and window. Raise AnalysisError on failure."""

    def window_for(self, now: datetime, params: dict) -> Window | None:
        """The time window a request at `now` covers. None for timeless analyses."""
        return None

    def key_for(self, geom: GEOSGeometry, window: Window | None, params: dict) -> str:
        return cache_key(self.name, self.version, geom, window, params)

    def run(self, geom: GEOSGeometry, params: dict | None = None, now: datetime | None = None):
        """Return the cached answer if fresh, otherwise compute, cache and return it."""
        params = dict(sorted((params or {}).items()))
        now = now or timezone.now()
        geom = canonical_geom(quantize(geom, self.grid_degrees))
        window = self.window_for(now, params)
        key = self.key_for(geom, window, params)

        hit = AnalysisResult.objects.filter(key=key, expires_at__gt=now).first()
        if hit is not None:
            return Outcome(hit.value, hit.provenance, True, key, hit.computed_at, hit.expires_at)

        computed = self.compute(geom, window, params)
        expires = now + self.ttl
        provenance = {
            **computed.provenance,
            "analysis": self.name,
            "version": self.version,
            "params": params,
            "computed_at": now.isoformat(),
        }
        AnalysisResult.objects.update_or_create(
            key=key,
            defaults={
                "analysis": self.name,
                "version": self.version,
                "geom": geom,
                "window_start": window.start if window else None,
                "window_end": window.end if window else None,
                "params": params,
                "value": computed.value,
                "provenance": provenance,
                "computed_at": now,
                "expires_at": expires,
            },
        )
        self.purge_expired(now)
        return Outcome(computed.value, provenance, False, key, now, expires)

    def purge_expired(self, now: datetime) -> int:
        """Delete this analysis's expired answers. An expired answer is never served, so
        keeping it would only turn a cache into an archive -- which, for weather, is
        exactly what CLAUDE.md says not to build."""
        deleted, _ = AnalysisResult.objects.filter(analysis=self.name, expires_at__lte=now).delete()
        return deleted
