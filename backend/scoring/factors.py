"""
The scoring factors. Each one turns a location into a FactorResult: a sub-score, the raw
measurement behind it, and a sentence explaining it -- so the overall score can always be
read factor by factor (docs/scoring.md).

A factor is a class registered in FACTORS under the key the config uses. Adding one
(weather, in TM05-44) means writing a class and adding its weight to config.yml; the
engine does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.gis.geos import Point

from geodata.distance import nearest, nearest_k
from geodata.models import PublicLand, Trail, WaterFeature
from scoring.curves import peak_curve

SCORED = "scored"
NO_DATA = "no_data"
NOT_AVAILABLE = "not_available"


@dataclass
class FactorResult:
    key: str
    label: str
    status: str
    score: float | None
    measurement: dict | None
    explanation: str
    caps: list[dict] = field(default_factory=list)


class Factor:
    """Base class. Subclasses set `key` and `label` and implement evaluate()."""

    key: str = ""
    label: str = ""

    def __init__(self, settings: dict):
        self.settings = settings

    def evaluate(self, lon: float, lat: float) -> FactorResult:
        raise NotImplementedError

    def result(self, status, score, measurement, explanation, caps=None) -> FactorResult:
        return FactorResult(
            key=self.key,
            label=self.label,
            status=status,
            score=None if score is None else max(0.0, min(100.0, score)),
            measurement=measurement,
            explanation=explanation,
            caps=caps or [],
        )


FACTORS: dict[str, type[Factor]] = {}


def register(cls: type[Factor]) -> type[Factor]:
    FACTORS[cls.key] = cls
    return cls


# --- water ---------------------------------------------------------------------------

WATER_NOUN = {
    "stream": "stream",
    "lake": "lake or pond",
    "wetland": "wetland",
    "spring": "spring",
    "other": "water feature",
}

# Flow class -> queryset filter. `perennial` is tri-state: null means the source did not
# say, which is scored as its own class rather than guessed.
FLOW_FILTERS = {
    "perennial": {"perennial": True},
    "intermittent": {"perennial": False},
    "unknown": {"perennial__isnull": True},
}


def _describe_water(water, flow: str) -> str:
    noun = WATER_NOUN.get(water.feature_type, "water feature")
    prefix = {"perennial": "Perennial ", "intermittent": "Intermittent "}.get(flow, "")
    text = f"{prefix}{noun}"
    return text[0].upper() + text[1:]


@register
class WaterFactor(Factor):
    key = "water"
    label = "Water"

    def evaluate(self, lon, lat):
        s = self.settings
        ideal, max_search = s["ideal_m"], s["max_search_m"]
        candidates = []
        for flow, filters in FLOW_FILTERS.items():
            queryset = WaterFeature.objects.filter(**filters)
            for water in nearest_k(queryset, lon, lat, s["candidates_per_class"]):
                if water.distance_m > max_search:
                    break
                curve = peak_curve(water.distance_m, ideal, s["at_zero"], s["half_distance_m"])
                multiplier = s["flow_multiplier"][flow] * s["feature_multiplier"].get(
                    water.feature_type, s["feature_multiplier"]["other"]
                )
                candidates.append((curve * multiplier, water, flow))

        if not candidates:
            return self.result(
                NO_DATA,
                0.0,
                {"distance_m": None, "ideal_m": ideal, "max_search_m": max_search},
                f"No mapped water within {max_search / 1000:g} km.",
            )

        score, best, flow = max(candidates, key=lambda candidate: candidate[0])
        closest = min(candidates, key=lambda candidate: candidate[1].distance_m)
        measurement = {
            "distance_m": round(best.distance_m, 1),
            "ideal_m": ideal,
            "feature_type": best.feature_type,
            "perennial": best.perennial,
            "name": best.name or None,
            "source": best.source,
            "source_id": best.source_id,
            "nearest_any_m": round(closest[1].distance_m, 1),
        }
        explanation = (
            f"{_describe_water(best, flow)} {best.distance_m:.0f} m away "
            f"(ideal is about {ideal:g} m)."
        )
        if closest[1].pk != best.pk:
            explanation += (
                f" Nearer water ({_describe_water(closest[1], closest[2]).lower()}, "
                f"{closest[1].distance_m:.0f} m) scored lower."
            )
        return self.result(SCORED, score, measurement, explanation)


# --- trail ---------------------------------------------------------------------------


@register
class TrailFactor(Factor):
    key = "trail"
    label = "Trail access"

    def evaluate(self, lon, lat):
        s = self.settings
        ideal, max_search = s["ideal_m"], s["max_search_m"]
        trail = nearest(Trail.objects.all(), lon, lat)
        if trail is None or trail.distance_m > max_search:
            return self.result(
                NO_DATA,
                0.0,
                {"distance_m": None, "ideal_m": ideal, "max_search_m": max_search},
                f"No mapped trail within {max_search / 1000:g} km.",
            )
        score = peak_curve(trail.distance_m, ideal, s["at_zero"], s["half_distance_m"])
        name = trail.name or None
        measurement = {
            "distance_m": round(trail.distance_m, 1),
            "ideal_m": ideal,
            "name": name,
            "trail_type": trail.trail_type or None,
            "source": trail.source,
            "source_id": trail.source_id,
        }
        what = name or "An unnamed trail"
        explanation = f"{what} is {trail.distance_m:.0f} m away (ideal is about {ideal:g} m)."
        return self.result(SCORED, score, measurement, explanation)


# --- legal ---------------------------------------------------------------------------

# Most restrictive first: when parcels overlap, the strictest access applies.
ACCESS_STRICTNESS = ["closed", "restricted", "unknown", "open"]

ACCESS_TEXT = {
    "open": "open to the public",
    "restricted": "restricted access",
    "unknown": "access status unknown",
    "closed": "closed to the public",
}


@register
class LegalFactor(Factor):
    key = "legal"
    label = "Legal status"

    def evaluate(self, lon, lat):
        s = self.settings
        point = Point(lon, lat, srid=4326)
        parcels = list(
            PublicLand.objects.filter(geom__intersects=point).only(
                "public_access", "gap_status", "manager", "designation", "name", "source_id"
            )
        )
        if not parcels:
            return self.result(
                NO_DATA,
                float(s["not_public_score"]),
                {
                    "public_access": None,
                    "gap_status": None,
                    "manager": None,
                    "designation": None,
                    "parcels": 0,
                },
                "Not inside any mapped public land, so probably private.",
            )

        access = min(
            (p.public_access for p in parcels),
            key=lambda value: ACCESS_STRICTNESS.index(value)
            if value in ACCESS_STRICTNESS
            else ACCESS_STRICTNESS.index("unknown"),
        )
        governing = [p for p in parcels if p.public_access == access]
        # Of the parcels that set the access, the best-protected GAP status describes
        # the land; blank (unknown) sorts last.
        parcel = min(governing, key=lambda p: p.gap_status or "9")
        gap = parcel.gap_status or ""
        score = s["access_score"].get(access, s["access_score"]["unknown"]) * s[
            "gap_multiplier"
        ].get(gap, s["gap_multiplier"][""])

        where = parcel.designation or parcel.name or parcel.manager or "public land"
        explanation = f"Inside {where}, {ACCESS_TEXT.get(access, access)}"
        explanation += f", GAP status {gap}." if gap else ", GAP status unknown."
        caps = []
        if access == "closed":
            caps.append(
                {
                    "factor": self.key,
                    "max_score": s["closed_caps_total_at"],
                    "reason": f"Inside land marked closed to the public ({where}).",
                }
            )
        measurement = {
            "public_access": access,
            "gap_status": gap or None,
            "manager": parcel.manager or None,
            "designation": parcel.designation or None,
            "parcels": len(parcels),
        }
        return self.result(SCORED, score, measurement, explanation, caps)


# --- placeholders --------------------------------------------------------------------


class PlaceholderFactor(Factor):
    """A factor whose data source is not built yet.

    Structured exactly like a real factor so Sprint 5 can replace the class without
    touching the engine or the output contract. Always not_available, so it is excluded
    from the total and the other weights are renormalised.
    """

    def evaluate(self, lon, lat):
        return self.result(
            NOT_AVAILABLE,
            None,
            None,
            self.settings.get("placeholder", f"{self.label} is not measured yet."),
        )


@register
class SlopeFactor(PlaceholderFactor):
    key = "slope"
    label = "Slope"


@register
class LandCoverFactor(PlaceholderFactor):
    key = "land_cover"
    label = "Land cover"
