"""
PAD-US adapter tests.

Almost everything here runs against `tests/fixtures/padus_page.json`, which was recorded
from a real response to a small Adirondack bounding box rather than hand-written, so the
tests break if the payload shape changes rather than only if our reading of it changes.
The fixture is trimmed to the five smallest features that still cover all four Pub_Access
codes and both geometry types the service emits.

The single test that touches the network is marked `network` and is deselected by default
(see pyproject addopts), so a USGS outage cannot turn CI red.
"""

import json
import pathlib
from unittest.mock import Mock, patch

import pytest
import requests
from django.contrib.gis.geos import GEOSGeometry

from geodata.models import IngestRun, PublicLand
from pipeline.adapters.padus import (
    PadusAdapter,
    PadusResponseError,
    UnknownPublicAccessCode,
)
from pipeline.aoi import AreaOfInterest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "padus_page.json"

# A small slice of the High Peaks, not the whole park -- keeps the live test quick.
SMALL_ADK = AreaOfInterest(
    name="adk-high-peaks",
    label="Adirondack High Peaks (test slice)",
    bbox=(-74.20, 44.00, -73.90, 44.20),
    states=("NY",),
)


@pytest.fixture
def page():
    """The recorded features, as fetch() would yield them: one page, a list of features."""
    return json.loads(FIXTURE.read_text())["features"]


@pytest.fixture
def adapter():
    return PadusAdapter()


def feature_with(page, **overrides):
    """A copy of the first recorded feature with some properties replaced."""
    feature = json.loads(json.dumps(page[0]))
    feature["properties"].update(overrides)
    return feature


# --- field mapping --------------------------------------------------------------------


@pytest.mark.unit
def test_the_fixture_still_covers_every_branch(page):
    """Guards the fixture itself: if it is ever re-recorded, it must stay representative."""
    assert {f["properties"]["Pub_Access"] for f in page} == {"OA", "RA", "UK", "XA"}
    assert {f["geometry"]["type"] for f in page} == {"Polygon", "MultiPolygon"}


@pytest.mark.unit
def test_fields_map_onto_the_model(adapter, page):
    records = list(adapter.normalize([page]))

    assert len(records) == len(page)
    record = records[0]
    source = page[0]["properties"]

    assert record["name"] == source["Unit_Nm"]
    assert record["manager"] == source["MngNm_Desc"]
    assert record["designation"] == source["DesTp_Desc"]
    assert isinstance(record["geom"], GEOSGeometry)
    assert record["geom"].srid == 4326


@pytest.mark.unit
def test_conservation_code_is_kept_in_raw_and_never_used_as_access(adapter, page):
    records = list(adapter.normalize([page]))

    for record in records:
        assert "GAP_Sts" in record["raw"], "GAP status must survive into raw"
        assert "MngTp_Desc" in record["raw"], "manager type belongs in raw, not a column"
        # GAP codes are "1".."4"; access values are the model's text choices. If GAP ever
        # leaked into public_access this would catch it.
        assert record["public_access"] not in {"1", "2", "3", "4"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,expected",
    [
        ("OA", PublicLand.Access.OPEN),
        ("RA", PublicLand.Access.RESTRICTED),
        ("XA", PublicLand.Access.CLOSED),
        ("UK", PublicLand.Access.UNKNOWN),
    ],
)
def test_every_public_access_code_maps(adapter, page, code, expected):
    record = adapter.to_record(feature_with(page, Pub_Access=code))

    assert record["public_access"] == expected


@pytest.mark.unit
@pytest.mark.parametrize("code", ["ZZ", "", None, "oa "])
def test_an_unexpected_access_code_fails_loudly(adapter, page, code):
    """A new upstream code must stop the run, not quietly become UNKNOWN."""
    if code == "oa ":
        # Whitespace and case are normalised, so this one should succeed instead.
        assert adapter.to_record(feature_with(page, Pub_Access=code))["public_access"] == (
            PublicLand.Access.OPEN
        )
        return

    with pytest.raises(UnknownPublicAccessCode) as err:
        adapter.to_record(feature_with(page, Pub_Access=code))

    message = str(err.value)
    assert "Known codes are OA, RA, UK, XA" in message
    assert "Unit_Nm" in message or page[0]["properties"]["Unit_Nm"] in message


@pytest.mark.unit
def test_normalize_leaves_polygon_coercion_to_the_framework(adapter, page):
    """The base class already promotes Polygon into a MultiPolygon column."""
    polygons = [f for f in page if f["geometry"]["type"] == "Polygon"]
    assert polygons, "fixture should contain at least one plain Polygon"

    record = adapter.to_record(polygons[0])

    assert record["geom"].geom_type == "Polygon", "normalize must not duplicate promotion"


@pytest.mark.unit
def test_a_feature_without_geometry_is_a_clear_error(adapter, page):
    broken = json.loads(json.dumps(page[0]))
    broken["geometry"] = None

    with pytest.raises(PadusResponseError, match="no geometry"):
        adapter.to_record(broken)


# --- synthesized identity -------------------------------------------------------------


@pytest.mark.unit
def test_source_id_is_deterministic_across_runs(adapter, page):
    first = [r["source_id"] for r in adapter.normalize([page])]
    second = [r["source_id"] for r in PadusAdapter().normalize([page])]

    assert first == second
    assert all(len(sid) == 64 for sid in first), "sha256 hex digest"


@pytest.mark.unit
def test_distinct_parcels_get_distinct_ids(adapter, page):
    ids = {r["source_id"] for r in adapter.normalize([page])}

    assert len(ids) == len(page)


@pytest.mark.unit
def test_source_id_survives_a_small_boundary_redraw(adapter, page):
    """The whole reason geometry is excluded from the hash.

    PAD-US re-digitizes boundaries between releases. A nudge far below the centroid
    rounding precision must not mint a new identifier and orphan the existing row.
    """
    original = page[0]
    nudged = json.loads(json.dumps(original))
    ring = nudged["geometry"]["coordinates"][0]
    moved = [ring[0][0] + 0.0000001, ring[0][1]]
    # A ring has to stay closed: first and last vertex are the same point.
    ring[0] = moved
    ring[-1] = moved

    assert adapter.to_record(nudged)["source_id"] == adapter.to_record(original)["source_id"]


@pytest.mark.unit
def test_source_id_changes_when_the_parcel_is_renamed(adapter, page):
    renamed = feature_with(page, Unit_Nm="Somewhere Else Entirely")

    assert adapter.to_record(renamed)["source_id"] != adapter.to_record(page[0])["source_id"]


# --- pagination -----------------------------------------------------------------------


def fake_response(payload, status=200, text=None):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.text = text if text is not None else json.dumps(payload)
    response.json = Mock(return_value=payload, side_effect=None)
    if payload is None:
        response.json = Mock(side_effect=ValueError("no json"))
    return response


def patch_session(responses):
    """Patch Session.get to return each prepared response in turn."""
    return patch.object(requests.Session, "get", side_effect=responses)


@pytest.mark.unit
def test_pagination_continues_while_more_data_is_reported(adapter, page):
    more = {"features": page, "properties": {"exceededTransferLimit": True}}
    last = {"features": page[:2], "properties": None}

    with patch_session([fake_response(more), fake_response(last)]) as get:
        pages = list(adapter.fetch(SMALL_ADK))

    assert [len(p) for p in pages] == [len(page), 2]
    assert get.call_count == 2
    # Offset advances by what actually arrived, not by page_size.
    assert get.call_args_list[1].kwargs["params"]["resultOffset"] == len(page)


@pytest.mark.unit
def test_pagination_does_not_stop_early_on_a_full_page(adapter, page):
    """A page that fills the request is not by itself the end."""
    full = {"features": page, "properties": {"exceededTransferLimit": True}}
    empty = {"features": [], "properties": None}

    with patch_session([fake_response(full), fake_response(empty)]) as get:
        pages = list(adapter.fetch(SMALL_ADK))

    assert len(pages) == 1
    assert get.call_count == 2


@pytest.mark.unit
def test_pagination_stops_on_an_empty_page_even_if_more_is_claimed(adapter):
    """Guards against looping forever when the flag and the data disagree."""
    lying = {"features": [], "properties": {"exceededTransferLimit": True}}

    with patch_session([fake_response(lying)]) as get:
        pages = list(adapter.fetch(SMALL_ADK))

    assert pages == []
    assert get.call_count == 1


@pytest.mark.unit
def test_pagination_refuses_to_loop_past_max_pages(adapter, page):
    endless = {"features": page, "properties": {"exceededTransferLimit": True}}

    with patch_session([fake_response(endless)] * (PadusAdapter.max_pages + 5)):
        with pytest.raises(PadusResponseError, match="Refusing to loop further"):
            list(adapter.fetch(SMALL_ADK))


@pytest.mark.unit
def test_the_request_asks_for_geojson_in_4326_with_a_user_agent(adapter, page):
    with patch_session([fake_response({"features": page, "properties": None})]) as get:
        list(adapter.fetch(SMALL_ADK))

    params = get.call_args.kwargs["params"]
    assert params["f"] == "geojson"
    assert params["outSR"] == 4326
    assert params["inSR"] == 4326
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert params["geometry"] == "-74.2,44.0,-73.9,44.2"
    assert "CampSite" in PadusAdapter.USER_AGENT


# --- error handling -------------------------------------------------------------------


@pytest.mark.unit
def test_a_non_200_is_reported_clearly(adapter):
    with patch_session([fake_response({}, status=503, text="upstream is down")]):
        with pytest.raises(PadusResponseError, match="HTTP 503"):
            list(adapter.fetch(SMALL_ADK))


@pytest.mark.unit
def test_a_non_json_body_is_reported_clearly(adapter):
    with patch_session([fake_response(None, text="<html>gateway timeout</html>")]):
        with pytest.raises(PadusResponseError, match="non-JSON"):
            list(adapter.fetch(SMALL_ADK))


@pytest.mark.unit
def test_an_arcgis_error_body_with_http_200_is_caught(adapter):
    """ArcGIS reports query errors in the body while still returning 200."""
    body = {"error": {"code": 400, "message": "Invalid or missing input parameters."}}

    with patch_session([fake_response(body)]):
        with pytest.raises(PadusResponseError, match="Invalid or missing input"):
            list(adapter.fetch(SMALL_ADK))


@pytest.mark.unit
def test_a_response_without_a_features_key_is_caught(adapter):
    with patch_session([fake_response({"type": "FeatureCollection"})]):
        with pytest.raises(PadusResponseError, match="no 'features' key"):
            list(adapter.fetch(SMALL_ADK))


@pytest.mark.unit
def test_a_connection_failure_is_wrapped(adapter):
    with patch.object(requests.Session, "get", side_effect=requests.ConnectionError("dns")):
        with pytest.raises(PadusResponseError, match="request failed"):
            list(adapter.fetch(SMALL_ADK))


# --- end to end against the database, with the network stubbed ------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_rows_land_in_postgis_with_promoted_geometry(page):
    adapter = PadusAdapter()

    with patch_session([fake_response({"features": page, "properties": None})]):
        run = adapter.run(SMALL_ADK)

    assert run.status == IngestRun.Status.SUCCESS
    assert run.record_count == len(page)
    assert PublicLand.objects.count() == len(page)

    for land in PublicLand.objects.all():
        assert land.geom.srid == 4326
        # Every row is a MultiPolygon even though some arrived as Polygon.
        assert land.geom.geom_type == "MultiPolygon"
        assert land.source == PublicLand.Source.PADUS
        assert land.last_run_id == run.pk
        assert land.raw, "the untouched source properties should be preserved"


@pytest.mark.django_db
@pytest.mark.integration
def test_running_twice_is_idempotent(page):
    adapter = PadusAdapter()
    responses = [fake_response({"features": page, "properties": None}) for _ in range(2)]

    with patch_session(responses[:1]):
        first = adapter.run(SMALL_ADK)
    with patch_session(responses[1:]):
        second = adapter.run(SMALL_ADK)

    assert PublicLand.objects.count() == len(page), "a rerun must update, not duplicate"
    assert IngestRun.objects.count() == 2, "both runs are recorded"
    assert first.pk != second.pk
    assert all(
        land.last_run_id == second.pk for land in PublicLand.objects.all()
    ), "rows should be re-stamped with the newer run"


@pytest.mark.django_db
@pytest.mark.integration
def test_an_unexpected_access_code_fails_the_run_and_records_it(page):
    poisoned = json.loads(json.dumps(page))
    poisoned[1]["properties"]["Pub_Access"] = "NEW"
    adapter = PadusAdapter()

    with patch_session([fake_response({"features": poisoned, "properties": None})]):
        with pytest.raises(UnknownPublicAccessCode):
            adapter.run(SMALL_ADK)

    run = IngestRun.objects.get()
    assert run.status == IngestRun.Status.FAILED
    assert "UnknownPublicAccessCode" in run.notes
    assert PublicLand.objects.count() == 0, "a failed run must not half-load"


# --- the one test that hits the live service ------------------------------------------


@pytest.mark.network
@pytest.mark.django_db
@pytest.mark.integration
def test_live_service_returns_usable_rows():
    """Hits USGS for real. Deselected by default; run with: pytest -m network

    Note the status assertion allows PARTIAL. Real PAD-US contains self-intersecting
    rings and nested shells -- about 19% of features in this bounding box -- which the
    framework skips and reports. That is a live data-quality question (see the adapter
    notes), not a failure of this adapter, so the test must not demand SUCCESS.
    """
    run = PadusAdapter().run(SMALL_ADK)

    assert run.status in {IngestRun.Status.SUCCESS, IngestRun.Status.PARTIAL}
    assert run.record_count > 0
    assert PublicLand.objects.count() == run.record_count

    if run.status == IngestRun.Status.PARTIAL:
        assert "invalid geometry" in run.notes, "a partial run must say what it dropped"

    for land in PublicLand.objects.all()[:20]:
        assert land.geom.srid == 4326
        assert land.geom.valid, land.geom.valid_reason
        assert land.geom.geom_type == "MultiPolygon"
        assert land.public_access in PublicLand.Access.values
        assert len(land.source_id) == 64
