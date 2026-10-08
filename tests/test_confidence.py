"""
Campsite confidence and provenance (TM05-77): each level, the operator kept separate from
the level, and the detail endpoint's `confidence` object with its date from IngestRun.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from geodata.confidence import (
    COMMUNITY_MAPPED,
    LIMITED_INFO,
    MIN_INFORMATIVE_TAGS,
    OFFICIAL,
    confidence_level,
    confidence_payload,
)
from geodata.models import Campsite, IngestRun

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def site(source="osm", source_id="node/1", name="", tags=None, run=None):
    return Campsite.objects.create(
        source=source,
        source_id=source_id,
        name=name,
        geom=Point(-73.95, 44.18, srid=4326),
        raw={"tags": tags or {}},
        last_run=run,
    )


def test_ridb_is_official():
    assert confidence_level(site("ridb", "campsite/73996", "Russell Pond"))[0] == OFFICIAL


def test_a_named_osm_site_is_community_mapped():
    assert confidence_level(site(name="Marcy Dam"))[0] == COMMUNITY_MAPPED


def test_an_unnamed_osm_site_with_enough_detail_is_community_mapped():
    tags = {"tourism": "camp_site", "backcountry": "yes", "fireplace": "yes"}
    assert MIN_INFORMATIVE_TAGS == 2
    assert confidence_level(site(tags=tags))[0] == COMMUNITY_MAPPED


@pytest.mark.parametrize(
    "tags",
    [
        {"tourism": "camp_site"},
        {"tourism": "camp_site", "backcountry": "yes"},
        # tourism and amenity are on every record; they do not count as detail.
        {"amenity": "shelter", "tourism": "camp_site", "note": "fix me"},
        # A blank value says nothing.
        {"tourism": "camp_site", "backcountry": "yes", "fireplace": " "},
    ],
)
def test_an_unnamed_osm_site_with_little_detail_is_limited_info(tags):
    level, reason = confidence_level(site(tags=tags))
    assert level == LIMITED_INFO
    assert "no name" in reason


def test_an_nysdec_operator_tag_does_not_make_an_osm_site_official():
    record = site(name="Lean-to #2", tags={"operator": "NYSDEC", "shelter_type": "lean_to"})
    payload = confidence_payload(record)
    assert payload["level"] == COMMUNITY_MAPPED
    assert payload["operator"] == "NYSDEC"
    assert payload["source_label"] == "OpenStreetMap"


def test_last_updated_comes_from_the_ingest_run():
    finished = datetime(2026, 10, 7, 21, 20, tzinfo=UTC)
    run = IngestRun.objects.create(
        source="osm",
        region="adirondacks",
        started_at=datetime(2026, 10, 7, 21, 19, tzinfo=UTC),
        finished_at=finished,
    )
    payload = confidence_payload(site(name="Marcy Dam", run=run))
    assert payload["last_updated"] == finished.isoformat()


def test_without_an_ingest_run_last_updated_falls_back_to_the_row():
    payload = confidence_payload(site(name="Marcy Dam"))
    assert payload["last_updated"] is not None


def test_the_detail_endpoint_serves_confidence():
    run = IngestRun.objects.create(
        source="ridb",
        region="white-mountains-nh",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        finished_at=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
    )
    site("ridb", "campsite/73996", "Russell Pond", run=run)

    body = APIClient().get("/api/campsites/campsite/73996/detail/").json()

    assert body["confidence"] == {
        "level": "official",
        "label": "Official listing",
        "reason": "Listed by Recreation.gov, the federal reservation system.",
        "source": "ridb",
        "source_label": "Recreation.gov (RIDB)",
        "operator": None,
        "last_updated": "2026-09-19T12:05:00+00:00",
    }
