"""
Pre-warming the campsite search for demo trails (TM05-104): how names resolve, that the
panel's own request is then answered from the cache, the printed timings, and the make
target.
"""

import copy
import json
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Polygon
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from analysis.analyses import elevation
from geodata.models import METRIC_SRID, PublicLand, Trail, TrailRoute
from planning.management.commands.prewarm_candidates import routes_for

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
X0, Y0 = 1_770_000.0, 2_550_000.0
CALLS = []


@pytest.fixture(autouse=True)
def flat_world(monkeypatch):
    forecast = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(forecast)
    )
    CALLS.clear()

    def post(points):
        CALLS.append(len(points))
        return {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1} for i in range(len(points))
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", post)
    ring = Polygon.from_bbox((X0 - 3000, Y0 - 3000, X0 + 9000, Y0 + 3000))
    ring.srid = METRIC_SRID
    PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id="padus/1",
        name="Test Wild Forest",
        public_access="open",
        geom=MultiPolygon(ring.transform(4326, clone=True), srid=4326),
    )


def geom(x0, x1, y=0.0):
    line = LineString((X0 + x0, Y0 + y), (X0 + x1, Y0 + y), srid=METRIC_SRID)
    return MultiLineString(line.transform(4326, clone=True), srid=4326)


def route(osm_id, name, length):
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id=f"relation/{osm_id}",
        osm_id=osm_id,
        name=name,
        geom=geom(0, length),
        length_m=length,
        member_way_ids=[osm_id * 10],
    )


def way(number, name, x0, x1, nodes, y=0.0):
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=f"way/{number}",
        name=name,
        geom=geom(x0, x1, y),
        length_m=abs(x1 - x0),
        osm_node_ids=nodes,
    )


def test_names_resolve_as_the_trail_panel_opens_them():
    route(1, "Van Hoevenberg Trail", 4000)
    route(2, "Mount Van Hoevenberg Trail", 2000)
    route(3, "Phelps Trail", 3000)
    route(4, "Upper Phelps Trail", 5000)
    # Exact name wins over a longer route that contains it.
    assert [r.osm_id for r in routes_for("phelps trail")] == [3]
    # Otherwise the longest route starting with it ("Mount Van ..." only contains it).
    assert [r.osm_id for r in routes_for("Van Hoevenberg")] == [1]
    # Otherwise the longest route containing it.
    assert [r.osm_id for r in routes_for("Hoevenberg Trail")] == [1]


def test_a_name_with_no_route_is_its_assembled_trails_each_once():
    way(10, "Deer Pond Trail", 0, 1000, [1, 2])
    way(11, "Deer Pond Trail", 1000, 2000, [2, 3])  # joins way/10
    way(12, "Deer Pond Trail", 5000, 5500, [8, 9], y=2000)  # a separate piece
    trails = routes_for("Deer Pond Trail")
    assert [t.source_id for t in trails] == ["assembled/way/10", "assembled/way/12"]
    assert routes_for("Nothing Like It") == []


def test_prewarming_caches_the_panels_own_request_and_prints_timings():
    route(1, "Van Hoevenberg Trail", 4000)
    out = StringIO()
    call_command("prewarm_candidates", "Van Hoevenberg", stdout=out)
    printed = out.getvalue()
    assert "Van Hoevenberg -> Van Hoevenberg Trail (relation/1, 2.5 mi)" in printed
    assert "profile" in printed and "campsites" in printed and " s  computed" in printed
    assert "within 500 m" in printed and "Done in" in printed

    calls = len(CALLS)
    body = APIClient().get("/api/routes/1/candidates/").json()
    assert body["cached"] is True  # the first click is instant
    assert len(CALLS) == calls  # and makes no 3DEP call

    again = StringIO()
    call_command("prewarm_candidates", "Van Hoevenberg", stdout=again)
    assert "cached" in again.getvalue() and "computed" not in again.getvalue()


def test_assembled_trails_are_warmed_for_the_way_a_user_clicks():
    way(10, "Deer Pond Trail", 0, 1000, [1, 2])
    way(11, "Deer Pond Trail", 1000, 2000, [2, 3])
    call_command("prewarm_candidates", "Deer Pond Trail", stdout=StringIO())
    # Clicking either way opens the same assembled trail, so both are warm.
    for clicked in ("way/10", "way/11"):
        assert APIClient().get(f"/api/trails/{clicked}/candidates/").json()["cached"] is True


def test_commas_separate_names_and_unknown_names_fail_after_the_rest():
    route(1, "Van Hoevenberg Trail", 4000)
    out = StringIO()
    with pytest.raises(CommandError, match="Not found: Atlantis Trail"):
        call_command("prewarm_candidates", "Atlantis Trail, Van Hoevenberg", stdout=out)
    assert "Atlantis Trail: no named trail by that name" in out.getvalue()
    assert "Van Hoevenberg Trail" in out.getvalue()  # the rest were still warmed


def test_the_corridor_can_be_chosen_and_is_checked():
    route(1, "Van Hoevenberg Trail", 4000)
    out = StringIO()
    call_command("prewarm_candidates", "Van Hoevenberg", "--within", "1000", stdout=out)
    assert "within 1000 m" in out.getvalue()
    with pytest.raises(CommandError, match="--within"):
        call_command("prewarm_candidates", "Van Hoevenberg", "--within", "0")


def test_make_prewarm_defaults_to_the_demo_trails():
    makefile = (ROOT / "Makefile").read_text()
    assert (
        "DEMO_TRAILS = Van Hoevenberg,Phelps Trail,Deer Pond Trail,Cheney Pond-Irishtown"
        in makefile
    )
    target = makefile[makefile.index("\nprewarm:") :]
    assert 'prewarm_candidates "$(TRAILS)"' in target.split("\n\n")[0]
