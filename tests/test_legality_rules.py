"""
Per-region camping rules (TM05-118): scoring/legality.yml, loaded by scoring/rules.py and
applied by scoring/verdict.py.

- The Adirondacks behave exactly as before: 1,920 inputs replay the verdicts the
  pre-TM05-118 code gave (tests/fixtures/adirondack_verdicts_pre_tm05_118.json).
- The White Mountains apply the White Mountain National Forest rules.
- Anywhere without rules is always Unknown, never Permitted.
- A malformed legality.yml fails at load.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from django.contrib.gis.geos import Point

from geodata.models import Campsite
from scoring.rules import LEGALITY_PATH, LegalityConfigError, legality, parse
from scoring.verdict import (
    NOT_PERMITTED,
    PERMITTED,
    UNKNOWN,
    designation,
    elevation_limits,
    legality_verdict,
    region_of,
    undesignated_rule,
)

FIXTURE = Path(__file__).parent / "fixtures" / "adirondack_verdicts_pre_tm05_118.json"
M_PER_FT = 1 / 3.28084

ADIRONDACK_PLACES = {"marcy_area": (-73.95, 44.15), "south_adk": (-74.6, 43.4)}
ADIRONDACK_SITES = {
    "osm_plain": ("osm", "unknown", {"tourism": "camp_site"}),
    "osm_designated_text": (
        "osm",
        "unknown",
        {"tourism": "camp_site", "description": "NYSDEC designated campsite."},
    ),
    "osm_dec_operator": ("osm", "unknown", {"tourism": "camp_site", "operator": "NYS DEC"}),
    "lean_to": ("osm", "lean_to", {"amenity": "shelter"}),
    "ridb": ("ridb", "designated", {}),
}
LAND_STATUS = {
    "open": {"status": "permitted", "reason": "Inside State Wilderness, open to the public."},
    "closed": {"status": "not_permitted", "reason": "Inside an easement, closed to the public."},
    "unknown": {"status": "unknown", "reason": "Restricted access."},
    "unscored": None,
}

WHITE_MOUNTAINS = (-71.4, 44.1)
GREEN_MOUNTAINS = (-72.9, 44.0)  # a regions.yml region with no camping rules yet
NOWHERE = (-90.0, 40.0)  # outside every region
OPEN = LAND_STATUS["open"]
CLOSED = LAND_STATUS["closed"]


def site(source="osm", site_type="unknown", tags=None, where=WHITE_MOUNTAINS):
    return Campsite(
        source=source,
        source_id="node/1",
        site_type=site_type,
        geom=Point(*where, srid=4326),
        raw={"tags": tags if tags is not None else {"tourism": "camp_site"}},
    )


def facts(feet=2000, land="White Mountain National Forest", **near):
    return SimpleNamespace(
        elevation_m=None if feet is None else feet * M_PER_FT,
        land_name=land,
        trail_name=near.get("trail_name", ""),
        trail_distance_m=near.get("trail_m"),
        water_name=near.get("water_name", ""),
        water_distance_m=near.get("water_m"),
    )


# --- the Adirondacks: identical to before ------------------------------------------------


def test_adirondack_verdicts_are_identical_to_before_tm05_118():
    frozen = json.loads(FIXTURE.read_text())
    mismatches = []
    for kind, place, feet, land, status, expected in frozen["cases"]:
        source, site_type, tags = ADIRONDACK_SITES[kind]
        campsite = site(source, site_type, tags, ADIRONDACK_PLACES[place])
        stored = (
            None
            if feet is None and land is None
            else SimpleNamespace(
                elevation_m=None if feet is None else feet * M_PER_FT, land_name=land or ""
            )
        )
        got = legality_verdict(campsite, stored, LAND_STATUS[status])
        if got != frozen["outputs"][expected]:
            mismatches.append((kind, place, feet, land, status))
    assert len(frozen["cases"]) == 1920
    assert mismatches == []


def test_the_adirondacks_keep_their_three_dec_rules():
    region = region_of(site(where=ADIRONDACK_PLACES["marcy_area"]))
    assert region.key == "adirondacks"
    assert [rule.id for rule in region.rules] == [
        "adirondack_4000",
        "high_peaks_3500",
        "designated_150",
    ]
    marcy = site(where=ADIRONDACK_PLACES["marcy_area"])
    assert elevation_limits(marcy, "High Peaks Wilderness") == [
        ("adirondack_4000", 4000.0),
        ("high_peaks_3500", 3500.0),
    ]


# --- the White Mountains ------------------------------------------------------------------


def test_a_recreation_gov_site_in_the_white_mountains_is_permitted():
    verdict = legality_verdict(site(source="ridb", site_type="designated"), facts(), OPEN)
    assert verdict["verdict"] == PERMITTED
    assert verdict["rule"] is None


@pytest.mark.parametrize(
    "operator, basis",
    [
        ("Appalachian Mountain Club", "Appalachian Mountain Club"),
        ("Randolph Mountain Club", "Randolph Mountain Club"),
        ("Dartmouth Outing Club", "Dartmouth Outing Club"),
    ],
)
def test_partner_run_sites_count_as_designated(operator, basis):
    campsite = site(tags={"tourism": "camp_site", "operator": operator})
    assert basis in designation(campsite)
    assert legality_verdict(campsite, facts(), OPEN)["verdict"] == PERMITTED


def test_a_dec_operator_is_only_evidence_in_new_york():
    tags = {"tourism": "camp_site", "operator": "NYS DEC"}
    assert designation(site(tags=tags)) is None
    assert designation(site(tags=tags, where=ADIRONDACK_PLACES["marcy_area"])) is not None


def test_an_undesignated_site_cites_the_quarter_mile_developed_sites_rule():
    verdict = legality_verdict(site(), facts(trail_m=500, trail_name="Some Trail"), OPEN)
    assert verdict["verdict"] == UNKNOWN
    assert verdict["rule"]["text"].startswith("1/4 mile FPA regulations apply")
    assert "fs.usda.gov" in verdict["rule"]["source"]
    assert "alpine zone" in verdict["reason"]


def test_inside_a_wilderness_trail_setback_is_unknown_never_not_permitted():
    near = facts(land="Pemigewasset Wilderness", trail_name="Franconia Brook Trail", trail_m=20)
    verdict = legality_verdict(site(), near, OPEN)
    assert verdict["verdict"] == UNKNOWN
    assert verdict["rule"]["text"].startswith("Pemigewasset/Presidential Dry River Wilderness")
    assert verdict["reason"].startswith("About 66 ft from Franconia Brook Trail.")


def test_just_outside_a_setback_is_too_close_to_call_and_well_outside_is_not_cited():
    edge = facts(land="Great Gulf Wilderness", trail_name="Great Gulf Trail", trail_m=70)
    assert "too close to the 200 ft setback" in legality_verdict(site(), edge, OPEN)["reason"]
    far = facts(land="Great Gulf Wilderness", trail_name="Great Gulf Trail", trail_m=80)
    assert legality_verdict(site(), far, OPEN)["rule"]["text"].startswith("1/4 mile FPA")


def test_a_wilderness_setback_does_not_apply_outside_wilderness():
    near = facts(land="White Mountain National Forest", trail_name="Some Trail", trail_m=5)
    assert legality_verdict(site(), near, OPEN)["rule"]["text"].startswith("1/4 mile FPA")


def test_named_fpa_trails_match_the_osm_spelling_too():
    near = facts(trail_name="Liberty Spring Trail", trail_m=20)
    rule = legality_verdict(site(), near, OPEN)["rule"]
    assert "Liberty Springs Trail" in rule["text"]


def test_a_quarter_mile_fpa_pond():
    near = facts(water_name="Unknown Pond", water_m=90)
    verdict = legality_verdict(site(), near, OPEN)
    assert verdict["verdict"] == UNKNOWN
    assert verdict["reason"].startswith("About 0.06 mi from Unknown Pond.")
    assert "Unknown Pond" in verdict["rule"]["text"]


def test_a_designated_site_is_exempt_from_setbacks():
    near = facts(land="Pemigewasset Wilderness", trail_name="Franconia Brook Trail", trail_m=5)
    assert legality_verdict(site(source="ridb"), near, OPEN)["verdict"] == PERMITTED


def test_an_area_closed_to_camping_is_not_permitted_and_a_designated_site_there_is_unknown():
    inside = facts(land="Bartlett Experimental Forest")
    verdict = legality_verdict(site(), inside, LAND_STATUS["unknown"])
    assert verdict["verdict"] == NOT_PERMITTED
    assert "Bartlett Experimental Forest" in verdict["rule"]["text"]
    shelter = site(site_type="lean_to")
    assert (
        legality_verdict(shelter, facts(land="Mount Chocorua Scenic Area"), OPEN)["verdict"]
        == UNKNOWN
    )


def test_no_white_mountain_rule_is_an_elevation_limit():
    assert elevation_limits(site(), "White Mountain National Forest") == []
    tall = legality_verdict(site(source="ridb"), facts(feet=4500), OPEN)
    assert tall["verdict"] == PERMITTED


def test_closed_land_in_the_white_mountains_is_still_not_permitted():
    assert legality_verdict(site(), facts(), CLOSED)["verdict"] == NOT_PERMITTED


# --- anywhere without rules: always Unknown -----------------------------------------------


@pytest.mark.parametrize("where", [GREEN_MOUNTAINS, NOWHERE])
@pytest.mark.parametrize("status", ["open", "closed", "unknown", "unscored"])
@pytest.mark.parametrize("kind", ["ridb", "lean_to", "osm_plain"])
def test_without_rules_every_site_is_unknown_never_permitted(where, status, kind):
    source, site_type, tags = ADIRONDACK_SITES[kind]
    verdict = legality_verdict(site(source, site_type, tags, where), facts(), LAND_STATUS[status])
    assert verdict["verdict"] == UNKNOWN
    assert verdict["label"] == "Unknown: check current rules"
    assert verdict["reason"].startswith("No camping rules are recorded for this area yet")
    assert verdict["rule"] is None


def test_without_rules_the_reason_still_says_what_is_known():
    ridb = site(source="ridb", where=NOWHERE)
    reason = legality_verdict(ridb, facts(), CLOSED)["reason"]
    assert "recorded as a designated site (listed by Recreation.gov)" in reason
    assert "marks this land closed" in reason
    assert undesignated_rule(ridb) is None
    assert elevation_limits(ridb, None) == []


# --- the file itself ---------------------------------------------------------------------


def raw_config():
    return yaml.safe_load(LEGALITY_PATH.read_text())


def test_every_rule_quotes_an_official_https_source():
    for region in legality().regions:
        assert region.authority
        for rule in region.rules:
            assert rule.text and rule.source_url.startswith("https://"), rule.id
        for item in region.unchecked:
            assert item["text"] and item["why"]


def test_the_config_has_no_unit_free_numbers():
    for region in raw_config()["regions"].values():
        for rule in region.get("rules", []):
            for key in ("limit", "distance"):
                if key in rule:
                    assert set(rule[key]) == {"value", "unit"}


@pytest.mark.parametrize(
    "break_it, message",
    [
        (lambda c: c.update(version=2), "version"),
        (lambda c: c["regions"]["adirondacks"]["rules"][0].update(kind="nope"), "kind"),
        (
            lambda c: c["regions"]["adirondacks"]["rules"][0].update(
                limit={"value": 4000, "unit": "cubits"}
            ),
            "unit",
        ),
        (lambda c: c["regions"]["adirondacks"]["rules"][0].update(source="nope"), "source"),
        (lambda c: c["regions"]["adirondacks"]["rules"].pop(), "exactly one"),
        (
            lambda c: c["regions"]["white-mountains-nh"]["rules"][0].pop("where"),
            "needs a `where`",
        ),
        (
            lambda c: c["regions"]["white-mountains-nh"]["rules"][2].update(**{"from": "road"}),
            "from",
        ),
        (lambda c: c["regions"]["adirondacks"]["area"].update(bbox=[1, 2]), "bbox"),
    ],
)
def test_a_malformed_config_fails_at_load(break_it, message):
    config = raw_config()
    break_it(config)
    with pytest.raises(LegalityConfigError, match=message):
        parse(config)


def test_a_new_region_needs_only_a_config_entry():
    config = raw_config()
    config["regions"]["somewhere"] = {
        "label": "Somewhere",
        "authority": {"name": "A parks authority", "short": "Parks"},
        "area": {"bbox": [10.0, 45.0, 11.0, 46.0]},
        "sources": {"rules": {"title": "Rules", "url": "https://example.org/rules"}},
        "rules": [
            {
                "id": "max_2000_m",
                "kind": "max_elevation",
                "limit": {"value": 2000, "unit": "m"},
                "text": "No camping above 2,000 m.",
                "source": "rules",
            },
            {
                "id": "fallback",
                "kind": "undesignated",
                "text": "Camping only at designated sites.",
                "source": "rules",
                "reason": "Not a designated site we can confirm.",
            },
        ],
    }
    region = parse(config).region_at(10.5, 45.5)
    assert region.key == "somewhere"
    assert region.of_kind("max_elevation")[0].limit.feet() == pytest.approx(6561.68, abs=0.01)
