"""
Tests for `manage.py refresh` (TM05-91, `make refresh REGION=<region>`).

Every step is stubbed: the command's job is the order, stopping on failure, and the
summary, not the steps themselves. Nothing touches the network.
"""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from geodata.models import IngestRun
from pipeline.management.commands import refresh

SOURCES = ["nhd-flowlines", "osm-campsites", "osm-routes", "osm-trails", "padus", "ridb"]


@pytest.fixture
def steps(monkeypatch):
    """Stub every step. Records the calls; an ingest writes an IngestRun of 10 rows.

    Set `steps.fail_on` to a step's command or source name to make that step raise.
    """

    class Steps:
        calls: list[tuple[str, ...]] = []
        fail_on: str | None = None

    Steps.calls = []

    def fake_call_command(*command, **kwargs):
        Steps.calls.append(command)
        failing = Steps.fail_on in command
        if command[0] == "ingest":
            IngestRun.objects.create(
                source=IngestRun._meta.get_field("source").choices[1][0],
                region=command[2],
                started_at=timezone.now(),
                record_count=3 if failing else 10,
                status=IngestRun.Status.FAILED if failing else IngestRun.Status.SUCCESS,
            )
        if failing:
            raise RuntimeError("Overpass is having a day")

    monkeypatch.setattr(refresh, "call_command", fake_call_command)
    monkeypatch.setattr(refresh, "list_adapters", lambda: list(SOURCES))
    monkeypatch.setenv("RIDB_API_KEY", "test-key")
    return Steps


def run(region="adirondacks"):
    out = StringIO()
    call_command("refresh", region, stdout=out)
    return out.getvalue()


def summary_row(output, step):
    table = output[output.rindex("step ") :]
    return next(line for line in table.splitlines() if line.startswith(step + " "))


@pytest.mark.unit
def test_every_registered_source_is_refreshed_in_dependency_order(monkeypatch):
    monkeypatch.setattr(refresh, "list_adapters", lambda: ["zzz-new", *SOURCES, "aaa-new"])

    names = refresh.ingest_sources()

    assert names[:6] == [
        "padus",
        "nhd-flowlines",
        "osm-trails",
        "osm-campsites",
        "ridb",
        "osm-routes",
    ]
    # A source this file has never heard of still runs, after the ordered ones.
    assert names[6:] == ["aaa-new", "zzz-new"]


@pytest.mark.unit
def test_the_shipped_sources_all_have_a_place_in_the_order():
    """Catches a new adapter being added without deciding where it runs."""
    from pipeline.adapters import list_adapters

    assert set(list_adapters()) <= set(refresh.INGEST_ORDER)


@pytest.mark.django_db
@pytest.mark.integration
def test_refresh_runs_ingests_then_profiles_then_enrichment(steps):
    run()

    assert steps.calls == [
        ("ingest", "padus", "adirondacks"),
        ("ingest", "nhd-flowlines", "adirondacks"),
        ("ingest", "osm-trails", "adirondacks"),
        ("ingest", "osm-campsites", "adirondacks"),
        ("ingest", "ridb", "adirondacks"),
        ("ingest", "osm-routes", "adirondacks"),
        ("build_trail_graph", "adirondacks"),  # TM05-137: the routing graph
        ("build_route_profiles", "adirondacks"),
        ("enrich_campsites", "adirondacks"),
        ("enrich_routes", "adirondacks"),
        ("terrain", "adirondacks"),  # TM05-141: terrain facts and zones
    ]


@pytest.mark.django_db
@pytest.mark.integration
def test_the_summary_shows_time_and_ingest_run_record_counts_per_step(steps):
    output = run()

    assert summary_row(output, "padus").split()[:4] == ["padus", "ok", "0.0", "10"]
    assert "IngestRun: success" in summary_row(output, "padus")
    # A step that writes no IngestRun has no record count to show.
    assert summary_row(output, "enrich").split()[:4] == ["enrich", "ok", "0.0", "-"]
    assert summary_row(output, "total").split()[-1] == "60"


@pytest.mark.django_db
@pytest.mark.integration
def test_record_counts_come_only_from_this_refresh_and_this_region(steps):
    IngestRun.objects.create(
        source="osm", region="adirondacks", started_at=timezone.now(), record_count=5000
    )

    output = run()

    assert summary_row(output, "total").split()[-1] == "60"


@pytest.mark.django_db
@pytest.mark.integration
def test_refresh_stops_at_the_first_failure_and_still_prints_the_summary(steps):
    steps.fail_on = "osm-trails"
    out = StringIO()

    with pytest.raises(CommandError) as error:
        call_command("refresh", "adirondacks", stdout=out)

    assert [command[1] for command in steps.calls] == ["padus", "nhd-flowlines", "osm-trails"]
    assert "Stopped at osm-trails: RuntimeError: Overpass is having a day" in str(error.value)
    assert "Not run: osm-campsites, ridb, osm-routes, trail-graph, route-profiles" in str(
        error.value
    )
    row = summary_row(out.getvalue(), "osm-trails")
    assert row.split()[:4] == ["osm-trails", "FAILED", "0.0", "3"]
    assert "osm-campsites" not in out.getvalue()


@pytest.mark.django_db
@pytest.mark.integration
def test_a_failing_enrichment_step_fails_the_refresh(steps):
    steps.fail_on = "enrich_campsites"

    with pytest.raises(CommandError, match="Stopped at enrich"):
        run()

    assert steps.calls[-1] == ("enrich_campsites", "adirondacks")


@pytest.mark.django_db
@pytest.mark.integration
def test_ridb_is_skipped_without_a_key_and_the_refresh_continues(steps, monkeypatch):
    monkeypatch.delenv("RIDB_API_KEY")

    output = run()

    assert ("ingest", "ridb", "adirondacks") not in steps.calls
    assert summary_row(output, "ridb").split()[:2] == ["ridb", "skipped"]
    assert steps.calls[-1] == ("terrain", "adirondacks")


@pytest.mark.django_db
def test_an_unknown_region_is_rejected_before_anything_runs(steps):
    with pytest.raises(CommandError, match="nowhere"):
        run("nowhere")

    assert steps.calls == []
