"""
RIDB adapter tests.

Fixtures were recorded from live responses around the White Mountains and written only
after asserting the API key does not appear anywhere in them. Nothing here reads
RIDB_API_KEY except the live test, which is marked `network` and deselected by default.

RIDB is the only source queried by circle rather than bounding box, so the
circle-to-tile conversion and the over-fetch filtering are the parts under most scrutiny.
"""

import json
import pathlib
from unittest.mock import Mock, patch

import pytest
import requests

from geodata.models import Campsite, IngestRun
from pipeline.adapters.ridb import (
    MAX_RADIUS_MILES,
    RidbAdapter,
    RidbAuthError,
    RidbClient,
    RidbResponseError,
    RidbUnavailable,
)
from pipeline.aoi import AreaOfInterest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# White Mountain National Forest -- USFS land, so RIDB actually has coverage here.
WHITE_MOUNTAINS = AreaOfInterest(
    name="white-mountains-nh",
    label="White Mountains",
    bbox=(-72.00, 43.85, -70.95, 44.55),
    states=("NH",),
)

# One tile-sized area around White Ledge Campground for the live test.
TINY = AreaOfInterest(
    name="wmnf-tiny",
    label="White Mountains test slice",
    bbox=(-71.45, 43.90, -70.95, 44.20),
    states=("NH",),
)


@pytest.fixture
def facilities():
    return json.loads((FIXTURES / "ridb_facilities_page.json").read_text())["RECDATA"]


@pytest.fixture
def campsites():
    return json.loads((FIXTURES / "ridb_campsites_page.json").read_text())["RECDATA"]


@pytest.fixture
def adapter():
    return RidbAdapter(client=Mock(spec=RidbClient))


def campground(facilities):
    return next(f for f in facilities if f["FacilityTypeDescription"] == "Campground")


def site_named(campsites, campsite_type):
    return next(c for c in campsites if c["CampsiteType"] == campsite_type)


def at(site, lon, lat):
    copy = json.loads(json.dumps(site))
    copy["CampsiteLongitude"], copy["CampsiteLatitude"] = lon, lat
    return copy


# --- the key must never leak ------------------------------------------------------------


@pytest.mark.unit
def test_no_fixture_contains_anything_resembling_a_key():
    """Belt and braces: fixtures were scrubbed at record time; verify it stayed that way."""
    for name in ("ridb_facilities_page.json", "ridb_campsites_page.json"):
        text = (FIXTURES / name).read_text()
        assert "apikey" not in text.lower()
        assert "RIDB_API_KEY" not in text


@pytest.mark.unit
def test_an_auth_failure_message_does_not_echo_the_key():
    client = RidbClient(api_key="super-secret-value", sleep=lambda _: None)
    response = Mock(spec=requests.Response, status_code=401, text="Unauthorized")

    with patch.object(requests.Session, "get", return_value=response):
        with pytest.raises(RidbAuthError) as err:
            client.get("/facilities", {})

    assert "super-secret-value" not in str(err.value)
    assert "RIDB_API_KEY" in str(err.value)


@pytest.mark.unit
def test_run_parameters_never_include_the_key():
    adapter = RidbAdapter(client=RidbClient(api_key="super-secret-value"))

    parameters = adapter.run_parameters(WHITE_MOUNTAINS)

    assert "super-secret-value" not in json.dumps(parameters)


@pytest.mark.unit
def test_a_missing_key_fails_before_any_request_is_made():
    with patch.dict("os.environ", {"RIDB_API_KEY": ""}, clear=False):
        with pytest.raises(RidbAuthError, match="RIDB_API_KEY is not set"):
            RidbClient()


# --- circle conversion --------------------------------------------------------------------


@pytest.mark.unit
def test_the_search_circle_is_centred_on_the_tile(adapter):
    latitude, longitude, radius = adapter.search_circle(WHITE_MOUNTAINS)

    assert longitude == pytest.approx(-71.475)
    assert latitude == pytest.approx(44.20)
    assert radius == MAX_RADIUS_MILES


@pytest.mark.unit
def test_a_non_square_bbox_still_centres_correctly(adapter):
    tall = AreaOfInterest(name="tall", label="Tall", bbox=(-72.0, 43.0, -71.8, 44.6))

    latitude, longitude, _ = adapter.search_circle(tall)

    assert longitude == pytest.approx(-71.9)
    assert latitude == pytest.approx(43.8)


@pytest.mark.unit
def test_the_radius_is_always_the_api_maximum(adapter):
    """Anything larger is silently clamped; anything smaller risks clipping a corner."""
    tiny = AreaOfInterest(name="t", label="T", bbox=(-71.0, 44.0, -70.99, 44.01))

    assert adapter.search_circle(tiny)[2] == MAX_RADIUS_MILES
    assert adapter.search_circle(WHITE_MOUNTAINS)[2] == MAX_RADIUS_MILES


@pytest.mark.unit
def test_tiles_fit_inside_the_radius_cap():
    """0.5 degrees is not a preference here -- it is forced by the 25 mile cap."""
    import math

    for latitude in (44.0, 47.5):  # Adirondacks through northern Maine
        height = RidbAdapter.max_tile_degrees * 69.0
        width = RidbAdapter.max_tile_degrees * 69.0 * math.cos(math.radians(latitude))
        assert math.hypot(height, width) / 2 <= MAX_RADIUS_MILES


# --- over-fetch filtering -------------------------------------------------------------------


@pytest.mark.unit
def test_a_result_outside_the_tile_is_dropped(adapter, campsites, facilities):
    outside = at(campsites[0], lon=-69.0, lat=41.0)  # well beyond the White Mountains

    assert adapter.to_record(outside, campground(facilities), WHITE_MOUNTAINS) is None


@pytest.mark.unit
def test_a_result_inside_the_tile_is_kept(adapter, campsites, facilities):
    inside = at(campsites[0], lon=-71.4, lat=44.2)

    record = adapter.to_record(inside, campground(facilities), WHITE_MOUNTAINS)

    assert record is not None
    assert record["geom"].x == pytest.approx(-71.4)


@pytest.mark.unit
def test_a_result_exactly_on_the_boundary_is_kept(adapter, campsites, facilities):
    """Inclusive bounds, so a site on a shared edge is not lost by both tiles."""
    corner = at(campsites[0], lon=WHITE_MOUNTAINS.min_lon, lat=WHITE_MOUNTAINS.min_lat)

    assert adapter.to_record(corner, campground(facilities), WHITE_MOUNTAINS) is not None


# --- missing coordinates ----------------------------------------------------------------------


@pytest.mark.unit
def test_zero_coordinates_are_treated_as_missing_not_as_a_location(adapter, campsites, facilities):
    """0/0 is in the Gulf of Guinea. Storing it would be worse than storing nothing."""
    zeroed = at(campsites[0], lon=0, lat=0)

    record = adapter.to_record(zeroed, campground(facilities), WHITE_MOUNTAINS)

    assert record is not None, "must be emitted so the framework counts it"
    assert record["geom"] is None


@pytest.mark.unit
def test_the_fixture_really_contains_zero_coordinate_sites(campsites):
    blank = [
        c for c in campsites if not c.get("CampsiteLatitude") or not c.get("CampsiteLongitude")
    ]

    assert blank, "fixture should exercise the blank-coordinate path"


@pytest.mark.unit
def test_blank_and_placed_sites_are_separated_by_normalize(campsites, facilities):
    """Blank-coordinate sites are emitted with geom=None so the framework counts them."""
    adapter = RidbAdapter(client=Mock(spec=RidbClient))
    ground = campground(facilities)
    placed = [at(c, lon=-71.4, lat=44.2) for c in campsites[:2]]
    blank = at(campsites[0], lon=0, lat=0)
    blank["CampsiteID"] = "no-coords-1"

    records = list(adapter.normalize([(WHITE_MOUNTAINS, ground, placed + [blank])]))

    assert len([r for r in records if r["geom"] is not None]) == 2
    assert len([r for r in records if r["geom"] is None]) == 1


# --- field mapping ----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "campsite_type,expected",
    [
        ("STANDARD NONELECTRIC", Campsite.SiteType.DESIGNATED),
        ("TENT ONLY NONELECTRIC", Campsite.SiteType.DESIGNATED),
        ("CABIN NONELECTRIC", Campsite.SiteType.DESIGNATED),
        ("WALK TO", Campsite.SiteType.PRIMITIVE),
        ("HIKE IN", Campsite.SiteType.PRIMITIVE),
        ("BOAT IN", Campsite.SiteType.PRIMITIVE),
        ("GROUP SHELTER NONELECTRIC", Campsite.SiteType.GROUP),
        ("GROUP STANDARD NONELECTRIC", Campsite.SiteType.GROUP),
        ("SHELTER NONELECTRIC", Campsite.SiteType.LEAN_TO),
        ("MANAGEMENT", Campsite.SiteType.UNKNOWN),
        ("SOMETHING BRAND NEW", Campsite.SiteType.UNKNOWN),
        ("", Campsite.SiteType.UNKNOWN),
        (None, Campsite.SiteType.UNKNOWN),
    ],
)
def test_site_type_mapping(campsite_type, expected):
    assert RidbAdapter.site_type_for({"CampsiteType": campsite_type}) == expected


@pytest.mark.unit
def test_group_wins_over_shelter():
    """A GROUP SHELTER is a group site, not a lean-to; rule order matters."""
    assert RidbAdapter.site_type_for({"CampsiteType": "GROUP SHELTER"}) == Campsite.SiteType.GROUP


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [(True, True), (False, False), (None, None), ("yes", None)],
)
def test_reservable_only_accepts_a_real_boolean(value, expected):
    assert RidbAdapter.reservable_for({"CampsiteReservable": value}) is expected


@pytest.mark.unit
def test_capacity_is_read_from_attributes(campsites):
    site = {"ATTRIBUTES": [{"AttributeName": "Max Num of People", "AttributeValue": "8"}]}

    assert RidbAdapter.capacity_for(site) == 8


@pytest.mark.unit
@pytest.mark.parametrize(
    "attributes",
    [
        [],
        [{"AttributeName": "Shade", "AttributeValue": "Yes"}],
        [{"AttributeName": "Max Num of People", "AttributeValue": ""}],
        [{"AttributeName": "Max Num of People", "AttributeValue": "0"}],
        [{"AttributeName": "Max Num of People", "AttributeValue": "lots"}],
    ],
)
def test_capacity_stays_null_rather_than_guessing(attributes):
    assert RidbAdapter.capacity_for({"ATTRIBUTES": attributes}) is None


@pytest.mark.unit
def test_source_id_uses_the_campsite_id(adapter, campsites, facilities):
    site = at(campsites[0], lon=-71.4, lat=44.2)

    record = adapter.to_record(site, campground(facilities), WHITE_MOUNTAINS)

    assert record["source_id"] == f"campsite/{site['CampsiteID']}"


@pytest.mark.unit
def test_raw_keeps_the_site_and_its_parent_facility(adapter, campsites, facilities):
    ground = campground(facilities)
    site = at(campsites[0], lon=-71.4, lat=44.2)

    record = adapter.to_record(site, ground, WHITE_MOUNTAINS)

    assert record["raw"]["campsite"]["CampsiteID"] == site["CampsiteID"]
    assert record["raw"]["facility_id"] == ground["FacilityID"]


# --- fetch: only campgrounds, and the hierarchy ------------------------------------------------


@pytest.mark.unit
def test_non_campground_facilities_are_skipped_before_any_site_request(facilities, campsites):
    """56 of 77 facilities near the White Mountains are not campgrounds."""
    client = Mock(spec=RidbClient)
    client.base_url = "https://stub.invalid/api/v1"
    calls = []

    def iter_records(path, params, page_size=50):
        calls.append(path)
        if path == "/facilities":
            return iter(facilities)
        return iter(campsites)

    client.iter_records = iter_records
    adapter = RidbAdapter(client=client)

    list(adapter.fetch(WHITE_MOUNTAINS))

    site_calls = [c for c in calls if c != "/facilities"]
    campgrounds = [f for f in facilities if f["FacilityTypeDescription"] == "Campground"]
    assert len(site_calls) == len(campgrounds)
    assert all(c.startswith("/facilities/") for c in site_calls)


# --- client behaviour ---------------------------------------------------------------------------


def http(status=200, body=None, text=None):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.text = text if text is not None else json.dumps(body)
    if body is None:
        response.json = Mock(side_effect=ValueError("not json"))
    else:
        response.json = Mock(return_value=body)
    return response


def stub_client(responses, **kwargs):
    kwargs.setdefault("sleep", lambda _: None)
    client = RidbClient(api_key="test-key-not-real", **kwargs)
    return client, patch.object(requests.Session, "get", side_effect=responses)


@pytest.mark.unit
def test_the_key_travels_in_the_apikey_header():
    client = RidbClient(api_key="test-key-not-real")

    assert client._session.headers["apikey"] == "test-key-not-real"


@pytest.mark.unit
def test_pagination_walks_until_total_count_is_reached():
    page1 = {"METADATA": {"RESULTS": {"TOTAL_COUNT": 3}}, "RECDATA": [{"a": 1}, {"a": 2}]}
    page2 = {"METADATA": {"RESULTS": {"TOTAL_COUNT": 3}}, "RECDATA": [{"a": 3}]}
    client, patcher = stub_client([http(body=page1), http(body=page2)])

    with patcher as get:
        records = list(client.iter_records("/facilities", {}, page_size=2))

    assert len(records) == 3
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"]["offset"] == 2


@pytest.mark.unit
def test_pagination_stops_on_an_empty_page():
    empty = {"METADATA": {"RESULTS": {"TOTAL_COUNT": 99}}, "RECDATA": []}
    client, patcher = stub_client([http(body=empty)])

    with patcher as get:
        assert list(client.iter_records("/facilities", {}, page_size=2)) == []
    assert get.call_count == 1


@pytest.mark.unit
def test_a_429_is_retried_then_succeeds():
    ok = {"METADATA": {"RESULTS": {"TOTAL_COUNT": 1}}, "RECDATA": [{"a": 1}]}
    client, patcher = stub_client([http(429, body={}, text="slow down"), http(body=ok)])

    with patcher as get:
        payload = client.get("/facilities", {})

    assert get.call_count == 2
    assert payload["RECDATA"][0]["a"] == 1


@pytest.mark.unit
def test_repeated_server_errors_give_up_with_a_useful_message():
    client, patcher = stub_client([http(503, body={}, text="down")] * 4, max_attempts=4)

    with patcher:
        with pytest.raises(RidbUnavailable) as err:
            client.get("/facilities", {})

    assert "no rate-limit headers" in str(err.value)


@pytest.mark.unit
def test_a_non_json_body_is_reported_clearly():
    client, patcher = stub_client([http(200, text="<html>gateway timeout</html>")])

    with patcher:
        with pytest.raises(RidbResponseError, match="non-JSON"):
            client.get("/facilities", {})


@pytest.mark.unit
def test_a_response_without_recdata_is_reported_clearly():
    client, patcher = stub_client([http(body={"METADATA": {}})])

    with patcher:
        with pytest.raises(RidbResponseError, match="no RECDATA"):
            client.get("/facilities", {})


# --- end to end -----------------------------------------------------------------------------------


def adapter_returning(facilities, campsites):
    client = Mock(spec=RidbClient)
    client.base_url = "https://stub.invalid/api/v1"

    def iter_records(path, params, page_size=50):
        return iter(facilities if path == "/facilities" else campsites)

    client.iter_records = iter_records
    return RidbAdapter(client=client)


@pytest.mark.django_db
@pytest.mark.integration
def test_campsites_land_in_postgis(facilities, campsites):
    placed = [at(c, lon=-71.4, lat=44.2) for c in campsites]
    for index, site in enumerate(placed):
        site["CampsiteID"] = f"site-{index}"
    adapter = adapter_returning(facilities, placed)

    run = adapter.run(TINY)

    assert run.record_count > 0
    assert Campsite.objects.count() == run.record_count
    for site in Campsite.objects.all():
        assert site.geom.srid == 4326
        assert site.geom.geom_type == "Point"
        assert site.source == Campsite.Source.RIDB
        assert site.site_type in Campsite.SiteType.values
        assert site.last_run_id == run.pk


@pytest.mark.django_db
@pytest.mark.integration
def test_blank_coordinates_are_reported_in_the_run_notes(facilities, campsites):
    placed = [at(c, lon=-71.4, lat=44.2) for c in campsites]
    for index, site in enumerate(placed):
        site["CampsiteID"] = f"site-{index}"
    placed[0] = at(placed[0], lon=0, lat=0)
    adapter = adapter_returning(facilities, placed)

    run = adapter.run(TINY)

    assert run.status == IngestRun.Status.PARTIAL
    assert "missing geom" in run.notes
    assert Campsite.objects.count() == len(placed) - 1


@pytest.mark.django_db
@pytest.mark.integration
def test_running_twice_is_idempotent(facilities, campsites):
    placed = [at(c, lon=-71.4, lat=44.2) for c in campsites]
    for index, site in enumerate(placed):
        site["CampsiteID"] = f"site-{index}"

    first = adapter_returning(facilities, placed).run(TINY)
    second = adapter_returning(facilities, placed).run(TINY)

    assert Campsite.objects.count() == first.record_count
    assert IngestRun.objects.count() == 2
    assert first.pk != second.pk
    assert all(s.last_run_id == second.pk for s in Campsite.objects.all())


# --- live ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.django_db
@pytest.mark.integration
def test_live_ridb_returns_white_mountain_campsites():
    """Hits Recreation.gov for real. Run with: pytest -m network

    Deliberately the White Mountains, not the Adirondacks: RIDB is federal-only and the
    Adirondacks are New York state land, so that region legitimately returns nothing.
    """
    run = RidbAdapter().run(TINY)

    assert run.status in {IngestRun.Status.SUCCESS, IngestRun.Status.PARTIAL}
    assert run.record_count > 0, "White Mountain National Forest is USFS land"
    assert "apikey" not in json.dumps(run.parameters).lower()

    for site in Campsite.objects.all()[:20]:
        assert site.geom.srid == 4326
        assert site.source_id.startswith("campsite/")
        assert TINY.min_lon <= site.geom.x <= TINY.max_lon, "over-fetch should be filtered"
        assert TINY.min_lat <= site.geom.y <= TINY.max_lat
        assert site.site_type in Campsite.SiteType.values
