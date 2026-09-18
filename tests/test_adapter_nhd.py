"""
USGS NHD adapter tests.

Fixtures were recorded from live responses to a small Adirondack bounding box, one per
layer, trimmed to the smallest feature per distinct fcode:

    nhd_flowline_page.json    lowercase field names, fcodes 46000 / 46003 / 46006
    nhd_waterbody_page.json   UPPERCASE field names, FTypes 390 / 436 / 466

The casing difference between the two is real and is the single easiest thing about this
source to get silently wrong, so it is asserted directly rather than assumed.

This is also the first adapter using tiling *and* pagination together, so their
composition is under test here as much as the mapping is.
"""

import json
import pathlib
from unittest.mock import Mock, patch

import pytest
import requests

from geodata.models import IngestRun, WaterFeature
from pipeline.adapters.nhd import (
    FLOWLINE_FCODES,
    NhdError,
    NhdFlowlinesAdapter,
    NhdWaterbodiesAdapter,
    UnknownFeatureCode,
)
from pipeline.aoi import AreaOfInterest
from pipeline.arcgis import ArcGisFeatureClient, ArcGisResponseError, case_insensitive

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

ADK = AreaOfInterest(
    name="adirondacks",
    label="Adirondack Park",
    bbox=(-75.40, 43.00, -73.30, 44.90),
    states=("NY",),
)

TINY = AreaOfInterest(
    name="adk-tiny",
    label="Adirondack test slice",
    bbox=(-74.10, 44.10, -74.05, 44.15),
    states=("NY",),
)


@pytest.fixture
def flowlines():
    return json.loads((FIXTURES / "nhd_flowline_page.json").read_text())["features"]


@pytest.fixture
def waterbodies():
    return json.loads((FIXTURES / "nhd_waterbody_page.json").read_text())["features"]


def stub_client(pages):
    client = Mock(spec=ArcGisFeatureClient)
    client.service_url = "https://stub.invalid/query"
    client.iter_pages = Mock(side_effect=lambda aoi, **kw: iter(pages))
    return client


def feature_with(feature, **overrides):
    """A copy with properties replaced, preserving the original key casing."""
    copy = json.loads(json.dumps(feature))
    for key, value in overrides.items():
        # Match whichever case this layer uses.
        existing = next((k for k in copy["properties"] if k.lower() == key.lower()), key)
        copy["properties"][existing] = value
    return copy


# --- the field-case trap ----------------------------------------------------------------


@pytest.mark.unit
def test_the_two_layers_really_do_differ_in_case(flowlines, waterbodies):
    """Guards the fixtures: if re-recorded, they must still capture the difference."""
    flowline_keys = set(flowlines[0]["properties"])
    waterbody_keys = set(waterbodies[0]["properties"])

    assert "fcode" in flowline_keys and "FCODE" not in flowline_keys
    assert "FCODE" in waterbody_keys and "fcode" not in waterbody_keys
    assert "gnis_name" in flowline_keys
    assert "GNIS_NAME" in waterbody_keys


@pytest.mark.unit
def test_case_folding_makes_both_layers_readable_the_same_way(flowlines, waterbodies):
    assert case_insensitive(flowlines[0]["properties"])["fcode"] is not None
    assert case_insensitive(waterbodies[0]["properties"])["fcode"] is not None


@pytest.mark.unit
def test_uppercase_waterbody_fields_do_not_produce_nulls(waterbodies):
    """The failure mode this guards: reading FCODE as fcode yields None, not an error."""
    record = NhdWaterbodiesAdapter(client=stub_client([])).to_record(waterbodies[0])

    assert record["source_id"], "PERMANENT_IDENTIFIER must survive the case difference"
    assert record["feature_type"], "FTYPE must survive the case difference"
    assert record["geom"] is not None


@pytest.mark.unit
def test_lowercase_flowline_fields_are_read_correctly(flowlines):
    record = NhdFlowlinesAdapter(client=stub_client([])).to_record(flowlines[0])

    assert record["source_id"]
    assert record["feature_type"] == WaterFeature.FeatureType.STREAM


# --- flowline classification ------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "fcode,expected",
    [
        pytest.param(46006, True, id="perennial"),
        pytest.param(46003, False, id="intermittent"),
        pytest.param(46007, False, id="ephemeral"),
        pytest.param(46000, None, id="unqualified-is-unknown-not-false"),
    ],
)
def test_flowline_fcode_maps_to_perennial(flowlines, fcode, expected):
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    record = adapter.to_record(feature_with(flowlines[0], fcode=fcode))

    assert record["perennial"] is expected


@pytest.mark.unit
def test_unqualified_flowlines_are_unknown_rather_than_not_perennial(flowlines):
    """46000 means nobody recorded the flow regime, which is not the same as dry."""
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    record = adapter.to_record(feature_with(flowlines[0], fcode=46000))

    assert record["perennial"] is None
    assert record["perennial"] is not False


@pytest.mark.unit
def test_every_flowline_is_classified_as_a_stream(flowlines):
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    for record in adapter.normalize([flowlines]):
        assert record["feature_type"] == WaterFeature.FeatureType.STREAM


@pytest.mark.unit
def test_an_unexpected_flowline_fcode_fails_loudly(flowlines):
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    with pytest.raises(UnknownFeatureCode) as err:
        adapter.to_record(feature_with(flowlines[0], fcode=55800))

    assert "55800" in str(err.value)
    assert "Map it deliberately" in str(err.value)


@pytest.mark.unit
def test_the_server_side_filter_covers_exactly_the_mapped_codes():
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    for code in FLOWLINE_FCODES:
        assert str(code) in adapter.where_clause
    assert adapter.where_clause.startswith("fcode IN (")


# --- waterbody classification -----------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "ftype,expected",
    [
        pytest.param(390, WaterFeature.FeatureType.LAKE, id="lake-pond"),
        pytest.param(436, WaterFeature.FeatureType.LAKE, id="reservoir"),
        pytest.param(466, WaterFeature.FeatureType.WETLAND, id="swamp-marsh"),
        pytest.param(493, WaterFeature.FeatureType.OTHER, id="estuary"),
        pytest.param(378, WaterFeature.FeatureType.OTHER, id="ice-mass"),
        pytest.param(361, WaterFeature.FeatureType.OTHER, id="playa"),
    ],
)
def test_waterbody_ftype_maps_to_feature_type(waterbodies, ftype, expected):
    adapter = NhdWaterbodiesAdapter(client=stub_client([]))

    record = adapter.to_record(feature_with(waterbodies[0], FTYPE=ftype))

    assert record["feature_type"] == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "fcode,expected",
    [
        pytest.param(39004, True, id="lake-perennial"),
        pytest.param(39001, False, id="lake-intermittent"),
        pytest.param(39000, None, id="lake-unqualified"),
        pytest.param(46602, True, id="marsh-perennial"),
        pytest.param(46601, False, id="marsh-intermittent"),
        pytest.param(43624, None, id="reservoir-construction-code-says-nothing"),
    ],
)
def test_waterbody_fcode_maps_to_perennial(waterbodies, fcode, expected):
    adapter = NhdWaterbodiesAdapter(client=stub_client([]))

    record = adapter.to_record(feature_with(waterbodies[0], FCODE=fcode))

    assert record["perennial"] is expected


@pytest.mark.unit
def test_an_unmapped_waterbody_ftype_fails_loudly(waterbodies):
    adapter = NhdWaterbodiesAdapter(client=stub_client([]))

    with pytest.raises(UnknownFeatureCode) as err:
        adapter.to_record(feature_with(waterbodies[0], FTYPE=999))

    assert "999" in str(err.value)
    assert "defaulting to OTHER" in str(err.value)


# --- shared mapping ----------------------------------------------------------------------


@pytest.mark.unit
def test_permanent_identifier_is_used_verbatim_as_source_id(flowlines):
    adapter = NhdFlowlinesAdapter(client=stub_client([]))
    expected = flowlines[0]["properties"]["permanent_identifier"]

    assert adapter.to_record(flowlines[0])["source_id"] == expected


@pytest.mark.unit
def test_a_feature_without_a_permanent_identifier_is_rejected(flowlines):
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    with pytest.raises(NhdError, match="no permanent_identifier"):
        adapter.to_record(feature_with(flowlines[0], permanent_identifier=None))


@pytest.mark.unit
def test_a_feature_without_geometry_is_rejected(flowlines):
    broken = json.loads(json.dumps(flowlines[0]))
    broken["geometry"] = None
    adapter = NhdFlowlinesAdapter(client=stub_client([]))

    with pytest.raises(NhdError, match="no geometry"):
        adapter.to_record(broken)


@pytest.mark.unit
def test_geometry_is_tagged_4326_despite_a_null_crs_in_the_payload(flowlines, waterbodies):
    """The service sends "crs": null, so the SRID must come from the outSR we asked for."""
    assert json.loads((FIXTURES / "nhd_flowline_page.json").read_text())["crs"] is None

    line = NhdFlowlinesAdapter(client=stub_client([])).to_record(flowlines[0])
    polygon = NhdWaterbodiesAdapter(client=stub_client([])).to_record(waterbodies[0])

    assert line["geom"].srid == 4326
    assert polygon["geom"].srid == 4326
    assert line["geom"].geom_type == "LineString"
    assert polygon["geom"].geom_type == "Polygon"


@pytest.mark.unit
def test_raw_keeps_the_source_properties(flowlines):
    record = NhdFlowlinesAdapter(client=stub_client([])).to_record(flowlines[0])

    assert record["raw"]["reachcode"]
    assert "fcode" in record["raw"]


# --- pagination (the shared ArcGIS client) -----------------------------------------------


def http_response(status=200, body=None, text=None):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.text = text if text is not None else json.dumps(body)
    if body is None:
        response.json = Mock(side_effect=ValueError("not json"))
    else:
        response.json = Mock(return_value=body)
    return response


def client_with(responses):
    client = ArcGisFeatureClient("https://stub.invalid/query", page_size=2)
    return client, patch.object(requests.Session, "get", side_effect=responses)


@pytest.mark.unit
def test_nhd_reports_exceeded_transfer_limit_at_the_top_level(flowlines):
    """Unlike PAD-US, which nests it under "properties"."""
    more = {"features": flowlines[:2], "exceededTransferLimit": True}
    done = {"features": flowlines[2:]}
    client, patcher = client_with([http_response(body=more), http_response(body=done)])

    with patcher as get:
        pages = list(client.iter_pages(TINY))

    assert [len(p) for p in pages] == [2, len(flowlines) - 2]
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"]["resultOffset"] == 2


@pytest.mark.unit
def test_pagination_stops_on_an_empty_page(flowlines):
    full = {"features": flowlines[:2], "exceededTransferLimit": True}
    empty = {"features": [], "exceededTransferLimit": True}
    client, patcher = client_with([http_response(body=full), http_response(body=empty)])

    with patcher as get:
        pages = list(client.iter_pages(TINY))

    assert len(pages) == 1
    assert get.call_count == 2


@pytest.mark.unit
def test_an_arcgis_error_inside_a_200_is_caught():
    body = {"error": {"code": 400, "message": "Invalid or missing input parameters."}}
    client, patcher = client_with([http_response(body=body)])

    with patcher:
        with pytest.raises(ArcGisResponseError, match="Invalid or missing input"):
            list(client.iter_pages(TINY))


@pytest.mark.unit
def test_a_non_200_is_reported_clearly():
    client, patcher = client_with([http_response(503, body={}, text="service down")])

    with patcher:
        with pytest.raises(ArcGisResponseError, match="HTTP 503"):
            list(client.iter_pages(TINY))


@pytest.mark.unit
def test_a_non_json_body_is_reported_clearly():
    client, patcher = client_with([http_response(200, text="<html>gateway</html>")])

    with patcher:
        with pytest.raises(ArcGisResponseError, match="non-JSON"):
            list(client.iter_pages(TINY))


@pytest.mark.unit
def test_the_query_requests_geojson_in_4326_with_the_layer_filter():
    adapter = NhdFlowlinesAdapter()
    params = adapter.client.query_params(TINY, 0, where=adapter.where_clause, out_fields="*")

    assert params["f"] == "geojson"
    assert params["outSR"] == 4326 and params["inSR"] == 4326
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert "46006" in params["where"]
    assert adapter.client.service_url.endswith("/6/query")
    assert NhdWaterbodiesAdapter().client.service_url.endswith("/12/query")


# --- tiling and pagination together -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_the_adirondacks_split_into_twenty_tiles(flowlines):
    client = stub_client([])
    adapter = NhdFlowlinesAdapter(client=client)

    adapter.run(ADK)

    # 2.1 x 1.9 degrees at 0.5 -> 5 columns x 4 rows.
    assert client.iter_pages.call_count == 20
    areas = [call.args[0] for call in client.iter_pages.call_args_list]
    assert len({a.bbox for a in areas}) == 20


@pytest.mark.django_db
@pytest.mark.integration
def test_tiling_and_pagination_compose(flowlines):
    """Tiles split the area; resultOffset pages within each tile. Both, at once."""
    client = Mock(spec=ArcGisFeatureClient)
    client.service_url = "https://stub.invalid/query"
    # Two pages per tile, exercising paging inside every tile.
    client.iter_pages = Mock(side_effect=lambda aoi, **kw: iter([flowlines[:2], flowlines[2:]]))
    adapter = NhdFlowlinesAdapter(client=client)

    run = adapter.run(ADK)

    assert client.iter_pages.call_count == 20, "tiling still drives one call per tile"
    # Every tile returns the same features, so cross-tile dedup collapses them to one set.
    assert WaterFeature.objects.count() == len(flowlines)
    assert run.record_count == len(flowlines)
    assert run.status == IngestRun.Status.SUCCESS


@pytest.mark.django_db
@pytest.mark.integration
def test_a_feature_straddling_a_tile_boundary_becomes_one_row(flowlines):
    shared = [flowlines[0]]
    adapter = NhdFlowlinesAdapter(client=stub_client([shared]))

    run = adapter.run(ADK)

    assert WaterFeature.objects.count() == 1
    assert run.record_count == 1


# --- end to end ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.integration
def test_flowlines_land_in_postgis(flowlines):
    adapter = NhdFlowlinesAdapter(client=stub_client([flowlines]))

    run = adapter.run(ADK)

    assert run.record_count == len(flowlines)
    for water in WaterFeature.objects.all():
        assert water.geom.srid == 4326
        assert water.geom.geom_type == "LineString", "generic column keeps the real type"
        assert water.feature_type == WaterFeature.FeatureType.STREAM
        assert water.source == WaterFeature.Source.NHD
        assert water.last_run_id == run.pk


@pytest.mark.django_db
@pytest.mark.integration
def test_waterbodies_land_in_postgis_as_polygons(waterbodies):
    adapter = NhdWaterbodiesAdapter(client=stub_client([waterbodies]))

    run = adapter.run(ADK)

    assert run.record_count == len(waterbodies)
    for water in WaterFeature.objects.all():
        assert water.geom.geom_type == "Polygon", "no promotion on a generic column"
        assert water.feature_type in {
            WaterFeature.FeatureType.LAKE,
            WaterFeature.FeatureType.WETLAND,
            WaterFeature.FeatureType.OTHER,
        }


@pytest.mark.django_db
@pytest.mark.integration
def test_both_layers_coexist_in_one_table(flowlines, waterbodies):
    """Two adapters, one model -- the source_ids must not collide."""
    NhdFlowlinesAdapter(client=stub_client([flowlines])).run(ADK)
    NhdWaterbodiesAdapter(client=stub_client([waterbodies])).run(ADK)

    assert WaterFeature.objects.count() == len(flowlines) + len(waterbodies)
    assert WaterFeature.objects.filter(feature_type="stream").count() == len(flowlines)


@pytest.mark.django_db
@pytest.mark.integration
def test_running_twice_is_idempotent(flowlines):
    first = NhdFlowlinesAdapter(client=stub_client([flowlines])).run(ADK)
    second = NhdFlowlinesAdapter(client=stub_client([flowlines])).run(ADK)

    assert WaterFeature.objects.count() == len(flowlines)
    assert IngestRun.objects.count() == 2
    assert first.pk != second.pk
    assert all(w.last_run_id == second.pk for w in WaterFeature.objects.all())


# --- live -----------------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.django_db
@pytest.mark.integration
def test_live_nhd_flowlines():
    """Hits USGS for real over one small valley. Run with: pytest -m network"""
    run = NhdFlowlinesAdapter().run(TINY)

    assert run.status in {IngestRun.Status.SUCCESS, IngestRun.Status.PARTIAL}
    assert run.record_count > 0
    for water in WaterFeature.objects.all()[:20]:
        assert water.geom.srid == 4326
        assert water.feature_type == WaterFeature.FeatureType.STREAM
        assert water.perennial in {True, False, None}
        assert water.source_id


@pytest.mark.network
@pytest.mark.django_db
@pytest.mark.integration
def test_live_nhd_waterbodies():
    run = NhdWaterbodiesAdapter().run(TINY)

    assert run.status in {IngestRun.Status.SUCCESS, IngestRun.Status.PARTIAL}
    assert run.record_count > 0
    for water in WaterFeature.objects.all()[:20]:
        assert water.geom.srid == 4326
        assert water.feature_type in WaterFeature.FeatureType.values
