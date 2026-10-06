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

    def canonical_params(self, params: dict) -> dict:
        """The parameters as they are keyed. Override to fill in defaults and normalise
        types, so {} and {"stencil_m": 10} and {"stencil_m": 10.0} -- the same request --
        share one cache entry instead of three."""
        return params

    def window_for(self, now: datetime, params: dict) -> Window | None:
        """The time window a request at `now` covers. None for timeless analyses."""
        return None

    def key_for(self, geom: GEOSGeometry, window: Window | None, params: dict) -> str:
        return cache_key(self.name, self.version, geom, window, params)

    def compute_many(
        self, geoms: list[GEOSGeometry], window: Window | None, params: dict
    ) -> list[Computed | AnalysisError]:
        """Compute several answers at once. Override when the source can batch (3DEP
        takes hundreds of points per request); the default computes one at a time. Return
        one entry per geometry, in order: a Computed, or the AnalysisError for that one."""
        results: list[Computed | AnalysisError] = []
        for geom in geoms:
            try:
                results.append(self.compute(geom, window, params))
            except AnalysisError as error:
                results.append(error)
        return results

    def _prepare(self, geom: GEOSGeometry, params: dict, now: datetime):
        geom = canonical_geom(quantize(geom, self.grid_degrees))
        window = self.window_for(now, params)
        return geom, window, self.key_for(geom, window, params)

    def _store(self, geom, window, key, params, computed: Computed, now: datetime) -> Outcome:
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
        return Outcome(computed.value, provenance, False, key, now, expires)

    @staticmethod
    def _hit(row: AnalysisResult) -> Outcome:
        return Outcome(row.value, row.provenance, True, row.key, row.computed_at, row.expires_at)

    @staticmethod
    def _fresh(key: str, now: datetime) -> Outcome | None:
        hit = AnalysisResult.objects.filter(key=key, expires_at__gt=now).first()
        return None if hit is None else Analysis._hit(hit)

    def lookup(
        self, geom: GEOSGeometry, params: dict | None = None, now: datetime | None = None
    ) -> Outcome | None:
        """The cached answer if one is fresh, otherwise None. Never computes, so it never
        calls the source: for requests that must answer from stored values only (TM05-45)."""
        params = dict(sorted(self.canonical_params(dict(params or {})).items()))
        now = now or timezone.now()
        _, _, key = self._prepare(geom, params, now)
        return self._fresh(key, now)

    def run(self, geom: GEOSGeometry, params: dict | None = None, now: datetime | None = None):
        """Return the cached answer if fresh, otherwise compute, cache and return it."""
        params = dict(sorted(self.canonical_params(dict(params or {})).items()))
        now = now or timezone.now()
        geom, window, key = self._prepare(geom, params, now)

        hit = self._fresh(key, now)
        if hit is not None:
            return hit

        computed = self.compute(geom, window, params)
        outcome = self._store(geom, window, key, params, computed, now)
        self.purge_expired(now)
        return outcome

    def run_many(
        self, geoms: list[GEOSGeometry], params: dict | None = None, now: datetime | None = None
    ) -> list[Outcome | AnalysisError]:
        """run() for many geometries: one cache lookup, then compute_many() for the misses.

        Results are in input order; a geometry that could not be computed gets its
        AnalysisError instead of an Outcome, and nothing is cached for it. Geometries that
        key the same (e.g. two points in one grid cell) are computed once.
        """
        params = dict(sorted(self.canonical_params(dict(params or {})).items()))
        now = now or timezone.now()
        prepared = [self._prepare(geom, params, now) for geom in geoms]
        keys = {key for _, _, key in prepared}
        hits = {
            row.key: self._hit(row)
            for row in AnalysisResult.objects.filter(key__in=keys, expires_at__gt=now)
        }

        misses: dict[str, tuple] = {}
        for geom, window, key in prepared:
            if key not in hits and key not in misses:
                misses[key] = (geom, window)
        if misses:
            # Windows can only differ by geometry for timeless analyses; batch per window.
            by_window: dict = {}
            for key, (geom, window) in misses.items():
                by_window.setdefault(window, []).append((key, geom))
            for window, items in by_window.items():
                computed = self.compute_many([geom for _, geom in items], window, params)
                for (key, geom), result in zip(items, computed, strict=True):
                    if isinstance(result, AnalysisError):
                        hits[key] = result
                    else:
                        hits[key] = self._store(geom, window, key, params, result, now)
            self.purge_expired(now)
        return [hits[key] for _, _, key in prepared]

    def purge_expired(self, now: datetime) -> int:
        """Delete this analysis's expired answers. An expired answer is never served, so
        keeping it would only turn a cache into an archive -- which, for weather, is
        exactly what CLAUDE.md says not to build."""
        deleted, _ = AnalysisResult.objects.filter(analysis=self.name, expires_at__lte=now).delete()
        return deleted
