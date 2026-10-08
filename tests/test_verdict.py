"""
The legality verdict (TM05-76 follow-up): designated sites, the NYS DEC elevation limits
for the Adirondacks and the High Peaks, closed land, and what stays Unknown.
"""

from types import SimpleNamespace

import pytest
from django.contrib.gis.geos import Point

from geodata.models import Campsite
from scoring.config import load
from scoring.verdict import (
    DESIGNATED_NEAR_TRAIL_NOTE,
    NOT_PERMITTED,
    PERMITTED,
    UNKNOWN,
    designation,
    legality_verdict,
)

M_PER_FT = 1 / 3.28084
MARCY_AREA = (-73.95, 44.15)  # inside the Adirondacks
WHITE_MOUNTAINS = (-71.4, 44.1)
OPEN = {"status": "permitted", "reason": "Inside State Wilderness, open to the public."}
CLOSED = {"status": "not_permitted", "reason": "Inside an easement, closed to the public."}


def site(source="osm", site_type="unknown", tags=None, where=MARCY_AREA):
    return Campsite(
        source=source,
        source_id="node/1",
        site_type=site_type,
        geom=Point(*where, srid=4326),
        raw={"tags": tags or {"tourism": "camp_site"}},
    )


def facts(feet, land="High Peaks Wilderness"):
    return SimpleNamespace(elevation_m=feet * M_PER_FT, land_name=land)


DESIGNATED = {"tourism": "camp_site", "description": "NYSDEC designated campsite."}


# --- designation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (site(source="ridb"), "listed by Recreation.gov"),
        (site(site_type="lean_to"), "a lean-to"),
        (site(tags=DESIGNATED), "described as a designated campsite in OpenStreetMap"),
        (site(tags={"operator": "NYS DEC"}), "mapped as operated by NYSDEC in OpenStreetMap"),
        (site(), None),
    ],
)
def test_designation_evidence(record, expected):
    assert designation(record) == expected


# --- verdicts ----------------------------------------------------------------------------


def test_a_designated_site_well_below_the_limits_is_permitted():
    verdict = legality_verdict(site(tags=DESIGNATED), facts(2750), OPEN)
    assert verdict["verdict"] == PERMITTED
    assert verdict["label"] == "Permitted · designated site"


def test_sno_bird_a_designated_site_at_4028_ft_is_unknown_not_permitted():
    verdict = legality_verdict(site(tags=DESIGNATED), facts(4028), OPEN)
    assert verdict["verdict"] == UNKNOWN
    assert verdict["label"] == "Unknown: check current rules"
    assert "4,000 ft" in verdict["reason"]
    assert verdict["rule"]["source"].startswith("https://dec.ny.gov/")


def test_an_undesignated_site_clearly_above_4000_ft_is_not_permitted():
    verdict = legality_verdict(site(), facts(4300, land="Some Wild Forest"), OPEN)
    assert verdict["verdict"] == NOT_PERMITTED
    assert verdict["rule"]["text"].startswith("Except in an emergency")


def test_an_undesignated_site_above_3500_ft_in_the_high_peaks_is_not_permitted():
    verdict = legality_verdict(site(), facts(3700), OPEN)
    assert verdict["verdict"] == NOT_PERMITTED
    assert verdict["rule"]["text"] == "No camping above 3,500 feet (except at lean-to)."


def test_a_lean_to_above_3500_ft_in_the_high_peaks_is_permitted():
    assert legality_verdict(site(site_type="lean_to"), facts(3700), OPEN)["verdict"] == PERMITTED


def test_3500_ft_outside_the_high_peaks_is_not_a_limit():
    verdict = legality_verdict(site(tags=DESIGNATED), facts(3700, land="Some Wild Forest"), OPEN)
    assert verdict["verdict"] == PERMITTED


def test_near_a_limit_an_undesignated_site_is_unknown():
    assert legality_verdict(site(), facts(3980, land="Wild Forest"), OPEN)["verdict"] == UNKNOWN


def test_an_undesignated_site_below_the_limits_is_unknown_never_permitted():
    verdict = legality_verdict(site(), facts(2000, land="Wild Forest"), OPEN)
    assert verdict["verdict"] == UNKNOWN
    assert verdict["rule"]["text"].startswith("Camping is prohibited within 150 feet")


def test_closed_land_is_not_permitted_and_a_designated_site_there_is_unknown():
    assert legality_verdict(site(), facts(2000), CLOSED)["verdict"] == NOT_PERMITTED
    assert legality_verdict(site(tags=DESIGNATED), facts(2000), CLOSED)["verdict"] == UNKNOWN


def test_a_designated_adirondack_site_with_no_elevation_is_unknown():
    assert legality_verdict(site(tags=DESIGNATED), None, OPEN)["verdict"] == UNKNOWN


def test_new_york_elevation_rules_do_not_apply_outside_the_adirondacks():
    ridb = site(source="ridb", where=WHITE_MOUNTAINS)
    verdict = legality_verdict(ridb, facts(4500, land="White Mountain NF"), None)
    assert verdict["verdict"] == PERMITTED


def trail_factor(result):
    return next(f for f in result["factors"] if f["key"] == "trail")


# --- wording -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_a_designated_site_near_a_trail_says_that_is_normal(monkeypatch):
    from django.contrib.gis.geos import LineString, MultiLineString

    from geodata.models import Trail
    from scoring.engine import score_campsite

    monkeypatch.setattr("analysis.analyses.weather.fetch_json", lambda url, params: {"daily": {}})
    lon, lat = MARCY_AREA
    Trail.objects.create(
        source="osm",
        source_id="way/1",
        name="Test Trail",
        geom=MultiLineString(LineString((lon - 0.01, lat), (lon + 0.01, lat)), srid=4326),
    )
    record = site(tags=DESIGNATED)
    record.save()
    trail = trail_factor(score_campsite(record, stored_only=True))
    assert trail["explanation"].endswith(DESIGNATED_NEAR_TRAIL_NOTE)

    record.raw = {"tags": {"tourism": "camp_site"}}
    record.save()
    trail = trail_factor(score_campsite(record, stored_only=True))
    assert DESIGNATED_NEAR_TRAIL_NOTE not in trail["explanation"]


def test_no_sprint_names_in_user_facing_factor_text():
    assert load().factor("land_cover")["placeholder"] == "Land cover isn't measured yet."
