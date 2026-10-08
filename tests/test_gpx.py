"""
Tests for the GPX export (TM05-79).

Every document is validated against the GPX 1.1 schema, vendored at
tests/fixtures/gpx-1.1.xsd (from https://www.topografix.com/GPX/1/1/gpx.xsd, unchanged), so
the tests never reach the network. Routes are straight lines in EPSG:5070 like
test_api_routes.py; 3DEP is stubbed with a known slope.
"""

import copy
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest
import xmlschema
from django.contrib.gis.geos import LineString, MultiLineString, Point
from rest_framework.test import APIClient

from analysis.analyses import elevation
from analysis.base import AnalysisError
from api.gpx import Waypoint, build_gpx, filename, track_points
from geodata.models import Campsite, Trail, TrailRoute

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = xmlschema.XMLSchema(FIXTURES / "gpx-1.1.xsd")
NS = {"g": "http://www.topografix.com/GPX/1/1"}
FORECAST = json.loads((FIXTURES / "open_meteo_forecast.json").read_text())

X0, Y0 = 1_770_000.0, 2_550_000.0


def parse(body: bytes) -> ET.Element:
    SCHEMA.validate(body.decode("utf-8"))  # raises with the schema error if invalid
    return ET.fromstring(body)


# --- builder (no database) ---------------------------------------------------------------


def test_builder_output_is_valid_gpx_with_lat_lon_in_gpx_order():
    track = [(-74.0, 44.1, 500.0), (-73.99, 44.11, 510.5), (-73.98, 44.12, None)]
    waypoints = [Waypoint(lon=-73.995, lat=44.105, name="Lean-to <3>", desc="Score 80/100")]
    root = parse(build_gpx("Test & Trail", track, waypoints, desc="x", link="https://x.org/"))

    assert root.get("version") == "1.1"
    first = root.find("g:trk/g:trkseg/g:trkpt", NS)
    # Latitude is the 44 and longitude the -74, whichever order they are written in.
    assert float(first.get("lat")) == pytest.approx(44.1)
    assert float(first.get("lon")) == pytest.approx(-74.0)
    assert first.find("g:ele", NS).text == "500.0"
    points = root.findall("g:trk/g:trkseg/g:trkpt", NS)
    assert points[2].find("g:ele", NS) is None  # unknown elevation is left out
    wpt = root.find("g:wpt", NS)
    assert float(wpt.get("lat")) == pytest.approx(44.105)
    assert wpt.find("g:name", NS).text == "Lean-to <3>"
    assert root.find("g:metadata/g:name", NS).text == "Test & Trail"
    bounds = root.find("g:metadata/g:bounds", NS)
    assert float(bounds.get("minlat")) == pytest.approx(44.1)
    assert float(bounds.get("maxlon")) == pytest.approx(-73.98)


def test_builder_time_is_utc_and_empty_documents_are_still_valid():
    body = build_gpx("Empty", [], [], now=datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC))
    root = parse(body)
    assert root.find("g:metadata/g:time", NS).text == "2026-10-08T12:00:00Z"
    assert root.find("g:trk", NS) is None


def test_track_merges_vertices_with_profile_samples_and_interpolates_elevation():
    line = LineString((X0, Y0), (X0 + 100, Y0), (X0 + 100, Y0 + 100), srid=5070)
    points = track_points(line, [0.0, 50.0, 150.0, 200.0], [100.0, 110.0, 130.0, 140.0])
    # Vertices at 0, 100, 200 m and samples at 0, 50, 150, 200 m: five distinct positions.
    assert len(points) == 5
    assert [p[2] for p in points] == pytest.approx([100.0, 110.0, 120.0, 130.0, 140.0])
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    assert all(-180 <= lon <= 180 for lon in lons) and all(-90 <= lat <= 90 for lat in lats)
    assert all(30 < lat < 50 for lat in lats)  # CONUS latitudes, not longitudes


def test_track_without_a_profile_is_the_line_vertices_with_no_elevation():
    line = LineString((X0, Y0), (X0 + 100, Y0), srid=5070)
    points = track_points(line, None, None)
    assert len(points) == 2
    assert all(p[2] is None for p in points)


def test_filename_is_a_safe_slug():
    assert filename("Van Hoevenberg Trail") == "van-hoevenberg-trail.gpx"
    assert filename("../../etc/passwd") == "etc-passwd.gpx"
    assert filename("") == "trail.gpx"


# --- endpoints ----------------------------------------------------------------------------


@pytest.fixture
def stubbed_network(monkeypatch):
    monkeypatch.setattr(
        "analysis.analyses.weather.fetch_json", lambda url, params: copy.deepcopy(FORECAST)
    )

    def sloped_3dep(points):
        return {
            "samples": [
                {"locationId": i, "value": str(500 + i), "resolution": 1, "attributes": {}}
                for i in range(len(points))
            ]
        }

    monkeypatch.setattr(elevation, "post_samples", sloped_3dep)


def metric_point(x, y):
    return Point(X0 + x, Y0 + y, srid=5070).transform(4326, clone=True)


def make_route(osm_id=1, name="Test Trail", length=4000):
    line = LineString((X0, Y0), (X0 + length, Y0), srid=5070)
    geom = MultiLineString(line, srid=5070).transform(4326, clone=True)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id=f"relation/{osm_id}",
        osm_id=osm_id,
        name=name,
        geom=geom,
        length_m=length,
        member_way_ids=[10],
    )


def make_site(source_id, along, off, name=None):
    return Campsite.objects.create(
        source=Campsite.Source.OSM,
        source_id=source_id,
        name=name if name is not None else source_id,
        geom=metric_point(along, off),
    )


@pytest.mark.django_db
@pytest.mark.integration
def test_route_gpx_has_the_track_with_elevations_and_campsites_as_named_waypoints(
    stubbed_network,
):
    make_route()
    make_site("node/1", 1000, 100, name="Lean-to One")
    make_site("node/2", 3000, -200, name="Tent Pad")
    make_site("node/3", 2000, 900)  # beyond 500 m: not included

    response = APIClient().get("/api/routes/1/gpx/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/gpx+xml"
    assert response["Content-Disposition"] == 'attachment; filename="test-trail.gpx"'
    root = parse(response.content)
    assert [w.find("g:name", NS).text for w in root.findall("g:wpt", NS)] == [
        "Lean-to One",
        "Tent Pad",
    ]
    points = root.findall("g:trk/g:trkseg/g:trkpt", NS)
    assert len(points) >= 2
    elevations = [float(p.find("g:ele", NS).text) for p in points]
    assert elevations[0] == pytest.approx(500.0)
    assert elevations == sorted(elevations)  # the stub climbs steadily
    start = metric_point(0, 0)
    assert float(points[0].get("lat")) == pytest.approx(start.y, abs=1e-5)
    assert float(points[0].get("lon")) == pytest.approx(start.x, abs=1e-5)


@pytest.mark.django_db
@pytest.mark.integration
def test_route_gpx_respects_the_campsite_distance(stubbed_network):
    make_route()
    make_site("node/3", 2000, 900, name="Far Camp")
    root = parse(APIClient().get("/api/routes/1/gpx/", {"campsites_within_m": 1000}).content)
    assert [w.find("g:name", NS).text for w in root.findall("g:wpt", NS)] == ["Far Camp"]
    assert APIClient().get("/api/routes/1/gpx/", {"campsites_within_m": "x"}).status_code == 400


@pytest.mark.django_db
@pytest.mark.integration
def test_route_gpx_without_elevation_is_still_valid(stubbed_network, monkeypatch):
    def down(points):
        raise AnalysisError("3DEP unavailable")

    monkeypatch.setattr(elevation, "post_samples", down)
    make_route()
    root = parse(APIClient().get("/api/routes/1/gpx/").content)
    points = root.findall("g:trk/g:trkseg/g:trkpt", NS)
    assert points and all(p.find("g:ele", NS) is None for p in points)
    assert "Elevation unavailable" in root.find("g:metadata/g:desc", NS).text


@pytest.mark.django_db
@pytest.mark.integration
def test_way_gpx_exports_the_clicked_ways_trail(stubbed_network):
    line = LineString((X0, Y0), (X0 + 2000, Y0), srid=5070).transform(4326, clone=True)
    Trail.objects.create(
        source=Trail.Source.OSM,
        source_id="way/77",
        name="Lonely Path",
        geom=MultiLineString(line, srid=4326),
        osm_node_ids=[1, 2],
    )
    response = APIClient().get("/api/trails/way/77/gpx/")
    assert response.status_code == 200
    root = parse(response.content)
    assert root.find("g:trk/g:name", NS).text == "Lonely Path"


@pytest.mark.django_db
@pytest.mark.integration
def test_unknown_route_gpx_is_404():
    assert APIClient().get("/api/routes/999/gpx/").status_code == 404
