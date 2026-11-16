"""
The keyword parser (TM05-170): the deterministic fallback when the language model isn't
available (no key, a timeout, an API error, or output that failed validation).

It reads a request with fixed patterns: numbers with units ("under 10 miles", "5 to 8 mi",
"2,000 ft of climbing"), nights ("two nights", "overnight", "weekend"), difficulty, route
type, campsites, water and shelter words, region names, and the asks CampSite can't
measure yet. Its output goes through the same `schema.validate()` as the model's. It never
guesses a region, a length or a weight that the words don't state.
"""

from __future__ import annotations

import re

from . import schema

NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "single": 1,
    "two": 2,
    "couple": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
NUM = r"(\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")"
MILES = r"(?:miles?|mi)\b"
FEET = r"(?:feet|foot|ft)\b"
#: Around a lone distance ("a 10 mile hike"): this fraction either side.
AROUND = 0.2

BELOW = r"(?:under|below|less than|at most|no more than|max(?:imum)?|up to|<)"
ABOVE = r"(?:over|above|more than|at least|min(?:imum)?|>)"

DIFFICULTY_WORDS = {
    "easy": r"\b(?:easy|gentle|beginner|casual|relaxed)\b",
    "moderate": r"\b(?:moderate|medium|intermediate)\b",
    "hard": r"\b(?:hard|strenuous|difficult|challenging|tough|steep)\b",
}
ROUTE_WORDS = {
    "loop": r"\bloops?\b",
    "out_and_back": r"\bout[- ](?:and|&)[- ]back\b",
    "point_to_point": (
        r"\b(?:point[- ]to[- ]point|one[- ]way|traverse|thru[- ]hike|through[- ]hike)\b"
    ),
}
REGION_WORDS = {
    "adirondacks": r"\b(?:adirondacks?|adk|high peaks)\b",
    "white-mountains-nh": r"\b(?:white mountains?|whites|new hampshire)\b",
    "green-mountains-vt": r"\b(?:green mountains?|vermont)\b",
    "maine": r"\bmaine\b",
}
WATER = (
    r"\b(?:lakes?|lakeside|lakeshore|ponds?|pondside|rivers?|riverside|streams?|waterfront"
    r"|water views?|by the water|on the water)\b"
)
SHELTERED = r"\b(?:sheltered|out of the wind|protected from (?:the )?wind|wind[- ]?protected)\b"
CAMPSITES = r"\b(?:campsites?|camp ?sites?|camping|camp|lean[- ]?tos?|tent sites?|backpacking)\b"
#: Asks CampSite can't measure yet, and the name it gives them back.
UNSUPPORTED = [
    (r"\b(?:crowds?|crowded|busy|quiet|solitude|few people|not many people)\b", "crowding"),
    (r"\b(?:dogs?|dog[- ]friendly|pets?)\b", "dog rules"),
    (r"\b(?:fishing|fish)\b", "fishing"),
    (r"\b(?:swimming|swim)\b", "swimming"),
    (r"\b(?:permits?|reservations?|reservable)\b", "permits and reservations"),
    (
        r"\b(?:easy access|parking|close to (?:the )?road|near (?:the|a) road|car camping"
        r"|accessible)\b",
        "easy access from the road",
    ),
    (r"\b(?:bugs?|mosquito(?:es)?|black ?fl(?:y|ies))\b", "bugs"),
    (r"\b(?:cell (?:service|signal|reception)|signal|reception)\b", "cell signal"),
    (r"\b(?:campfires?|fire rings?)\b", "campfire rules"),
    (r"\b(?:kid[- ]friendly|kids?|family[- ]friendly|stroller)\b", "kid-friendliness"),
    (r"\b(?:foliage|fall colou?rs|wildflowers?)\b", "seasonal scenery"),
]


def _value(token: str) -> float:
    return float(NUMBER_WORDS[token]) if token in NUMBER_WORDS else float(token)


def _clean(text: str) -> str:
    text = text.lower().replace(",", "")
    text = re.sub(r"(\d)\s*k\s*(?=ft|feet|foot)", r"\g<1>000 ", text)  # 2k ft
    return " ".join(text.split())


def _range(text: str, unit: str) -> tuple[float | None, float | None]:
    """(min, max) of a quantity in `unit` (MILES or FEET), or (None, None)."""
    found = re.search(rf"{NUM}\s*(?:-|to|–)\s*{NUM}\s*{unit}", text)
    if found:
        low, high = sorted((_value(found.group(1)), _value(found.group(2))))
        return low, high
    low = high = None
    below = re.search(rf"{BELOW}\s*{NUM}\s*{unit}", text)
    above = re.search(rf"{ABOVE}\s*{NUM}\s*{unit}", text)
    if below:
        high = _value(below.group(1))
    if above:
        low = _value(above.group(1))
    if below or above:
        return low, high
    lone = re.search(rf"\b{NUM}[- ]?{unit}", text)
    if lone and unit == MILES:
        value = _value(lone.group(1))
        return round(value * (1 - AROUND), 1), round(value * (1 + AROUND), 1)
    if lone and unit == FEET:
        # "2000 ft of climbing" reads as a ceiling: hikers name the most they'll climb.
        return None, _value(lone.group(1))
    return None, None


def _nights(text: str) -> int | None:
    if re.search(r"\bday[- ]hikes?\b|\bday trip\b|\bno overnight\b", text):
        return 0
    found = re.search(rf"\b{NUM}[- ]nights?\b", text)
    if found:
        return int(_value(found.group(1)))
    found = re.search(rf"\b{NUM}[- ]days?\b", text)
    if found and _value(found.group(1)) >= 2:
        return int(_value(found.group(1))) - 1
    if re.search(r"\bweekend\b", text):
        return 2
    if re.search(r"\b(?:overnight|overnighter|one night|a night)\b", text):
        return 1
    return None


def parse(text: str) -> dict:
    """The request a phrase makes, in the schema's shape, validated."""
    clean = _clean(text)
    out = schema.empty()
    out["min_length_mi"], out["max_length_mi"] = _range(clean, MILES)
    out["min_gain_ft"], out["max_gain_ft"] = _range(clean, FEET)
    flat = re.search(r"\bflat\b|\bno climbing\b|\blittle climbing\b", clean)
    if flat and out["max_gain_ft"] is None:
        out["max_gain_ft"] = 500.0
    out["difficulty"] = [d for d, pattern in DIFFICULTY_WORDS.items() if re.search(pattern, clean)]
    out["route_type"] = [r for r, pattern in ROUTE_WORDS.items() if re.search(pattern, clean)]
    out["nights"] = _nights(clean)
    if re.search(CAMPSITES, clean):
        out["has_campsites"] = True
    if re.search(WATER, clean):
        out["water_view"] = True
    if re.search(SHELTERED, clean):
        out["sheltered"] = True
    regions = [r for r, pattern in REGION_WORDS.items() if re.search(pattern, clean)]
    out["region"] = regions[0] if len(regions) == 1 and regions[0] in schema.regions() else None
    out["unsupported"] = [name for pattern, name in UNSUPPORTED if re.search(pattern, clean)][
        : schema.MAX_UNSUPPORTED
    ]
    # Lengths past the schema's range are not guessed at; they are left out.
    for key, cap in (
        ("min_length_mi", schema.MAX_LENGTH_MI),
        ("max_length_mi", schema.MAX_LENGTH_MI),
        ("min_gain_ft", schema.MAX_GAIN_FT),
        ("max_gain_ft", schema.MAX_GAIN_FT),
    ):
        if out[key] is not None and out[key] > cap:
            out[key] = None
    if out["nights"] is not None and out["nights"] > schema.MAX_NIGHTS:
        out["nights"] = None
    return schema.validate(out)
