"""
Derived campsite names in the trail list (TM05-71): the route API gives each listed site
the same display name and derived flag as the campsite detail endpoint.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.test import APIClient

from analysis.analyses import elevation
from enrichment.models import CampsiteFacts
from geodata.models import METRIC_SRID, Campsite, TrailRoute

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

X0, Y0 = 1_770_000.0, 2_550_000.0


@pytest.fixture(autouse=True)
def flat_3dep(monkeypatch):
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": "500", "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        },
    )


def route():
    line = LineString((X0, Y0), (X0 + 4000, Y0), srid=METRIC_SRID).transform(4326, clone=True)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/1",
        osm_id=1,
        name="Test Trail",
        geom=MultiLineString(line, srid=4326),
        length_m=4000,
        member_way_ids=[1],
    )


def site(source_id, along, name="", display_name=None, derived=False):
    point = Point(X0 + along, Y0 + 50, srid=METRIC_SRID).transform(4326, clone=True)
    campsite = Campsite.objects.create(source="osm", source_id=source_id, name=name, geom=point)
    if display_name is not None:
        CampsiteFacts.objects.create(
            campsite=campsite,
            method_version="1",
            computed_at=datetime(2026, 10, 7, tzinfo=UTC),
            display_name=display_name,
            display_name_derived=derived,
        )
    return campsite


def listed():
    items = APIClient().get("/api/routes/1/").json()["campsites"]["items"]
    return {item["id"]: item for item in items}


def test_a_named_site_keeps_its_own_name():
    route()
    site("named", 1000, name="Marcy Dam", display_name="Marcy Dam")
    item = listed()["named"]
    assert item["display_name"] == "Marcy Dam"
    assert item["display_name_derived"] is False


def test_an_unnamed_site_gets_the_derived_name_flagged():
    route()
    site("derived", 2000, display_name="Campsite near Calamity Brook", derived=True)
    item = listed()["derived"]
    assert item["name"] is None
    assert item["display_name"] == "Campsite near Calamity Brook"
    assert item["display_name_derived"] is True


def test_the_list_and_the_detail_endpoint_agree():
    route()
    site("derived", 2000, display_name="Campsite near Calamity Brook", derived=True)
    item = listed()["derived"]
    detail = APIClient().get("/api/campsites/derived/detail/").json()
    assert (item["display_name"], item["display_name_derived"]) == (
        detail["display_name"],
        detail["display_name_derived"],
    )


def test_an_unenriched_site_falls_back_to_its_source_name():
    route()
    site("raw", 3000, name="Lean-to #2")
    site("bare", 3500)
    items = listed()
    assert (items["raw"]["display_name"], items["raw"]["display_name_derived"]) == (
        "Lean-to #2",
        False,
    )
    assert items["bare"]["display_name"] is None
