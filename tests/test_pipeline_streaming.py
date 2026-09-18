"""
Streaming and tiling tests for the ingestion framework.

Two framework capabilities are covered here, both added before any real adapter exists
because retrofitting them afterwards would mean touching four adapters:

* streaming -- fetch and normalize may yield instead of returning, and load batches as
  records arrive, so peak memory does not scale with how much a source returns
* tiling -- an adapter may declare max_tile_degrees and have the framework split the
  area of interest, for sources that cannot serve a whole region in one request

Every adapter here is a throwaway defined in the test suite, as in
test_pipeline_adapters.py. Real adapters are TM05-13.
"""

from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point

from geodata.models import Campsite, IngestRun
from pipeline.adapters import SourceAdapter
from pipeline.aoi import AreaOfInterest

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

# 2.1 degrees wide by 1.9 tall, so max_tile_degrees=1.0 gives a 3 x 2 grid.
ADK = AreaOfInterest(
    name="adirondacks",
    label="Adirondack Park",
    bbox=(-75.40, 43.00, -73.30, 44.90),
    states=("NY",),
)

SOMEWHERE = Point(-74.05, 44.11, srid=4326)


def spy_on_bulk_create(events=None):
    """Patch Campsite.objects.bulk_create to record batch sizes, still writing rows."""
    sizes = []
    real = Campsite.objects.bulk_create

    def spy(objs, *args, **kwargs):
        sizes.append(len(objs))
        if events is not None:
            events.append(("flush", len(objs)))
        return real(objs, *args, **kwargs)

    return patch.object(Campsite.objects, "bulk_create", spy), sizes


# --- change 1: streaming --------------------------------------------------------------


def test_a_generator_adapter_runs_end_to_end_with_an_accurate_count(clean_registry):
    class GeneratorAdapter(SourceAdapter):
        name = "generator"
        source = Campsite.Source.RIDB
        model = Campsite

        def fetch(self, aoi):
            for i in range(25):
                yield {"id": i}

        def normalize(self, raw):
            for row in raw:
                yield {"source_id": f"gen-{row['id']}", "geom": SOMEWHERE.clone()}

    clean_registry.register(GeneratorAdapter)
    run = GeneratorAdapter().run(ADK)

    assert run.status == IngestRun.Status.SUCCESS
    assert run.record_count == 25
    assert Campsite.objects.count() == 25


def test_a_list_returning_adapter_still_works_unchanged(clean_registry):
    """Backward compatibility: a list is an iterable, so pre-refactor adapters are fine."""

    class ListAdapter(SourceAdapter):
        name = "list-based"
        source = Campsite.Source.RIDB
        model = Campsite

        def fetch(self, aoi):
            return [{"id": 1}, {"id": 2}]

        def normalize(self, raw):
            return [{"source_id": f"list-{r['id']}", "geom": SOMEWHERE.clone()} for r in raw]

    clean_registry.register(ListAdapter)
    run = ListAdapter().run(ADK)

    assert run.record_count == 2
    assert Campsite.objects.count() == 2


def test_load_writes_in_batches_rather_than_one_giant_insert(clean_registry):
    class BatchedAdapter(SourceAdapter):
        name = "batched"
        source = Campsite.Source.RIDB
        model = Campsite
        batch_size = 10

        def fetch(self, aoi):
            return range(25)

        def normalize(self, raw):
            for i in raw:
                yield {"source_id": f"batch-{i}", "geom": SOMEWHERE.clone()}

    clean_registry.register(BatchedAdapter)
    patcher, sizes = spy_on_bulk_create()

    with patcher:
        run = BatchedAdapter().run(ADK)

    # Three writes, not one -- and the remainder is flushed rather than dropped.
    assert sizes == [10, 10, 5]
    assert run.record_count == 25
    assert Campsite.objects.count() == 25


def test_records_are_consumed_lazily_not_materialised_first(clean_registry):
    """The first batch must be written before the source has finished producing."""
    events = []

    class LazyAdapter(SourceAdapter):
        name = "lazy"
        source = Campsite.Source.RIDB
        model = Campsite
        batch_size = 5

        def fetch(self, aoi):
            for i in range(12):
                events.append(("produce", i))
                yield i

        def normalize(self, raw):
            for i in raw:
                yield {"source_id": f"lazy-{i}", "geom": SOMEWHERE.clone()}

    clean_registry.register(LazyAdapter)
    patcher, _ = spy_on_bulk_create(events)

    with patcher:
        LazyAdapter().run(ADK)

    kinds = [kind for kind, _ in events]
    first_flush = kinds.index("flush")
    last_produce = len(kinds) - 1 - kinds[::-1].index("produce")

    assert first_flush < last_produce, (
        "a batch should be written before the source finishes producing; "
        f"got event order {kinds}"
    )
    assert Campsite.objects.count() == 12


def test_the_count_survives_a_source_with_no_length(clean_registry):
    """record_count is accumulated during load, never len() of the input."""

    class UncountableAdapter(SourceAdapter):
        name = "uncountable"
        source = Campsite.Source.RIDB
        model = Campsite

        def fetch(self, aoi):
            return (i for i in range(7))

        def normalize(self, raw):
            return ({"source_id": f"u-{i}", "geom": SOMEWHERE.clone()} for i in raw)

    clean_registry.register(UncountableAdapter)

    with pytest.raises(TypeError):
        len(UncountableAdapter().fetch(ADK))  # genuinely has no length

    assert UncountableAdapter().run(ADK).record_count == 7


# --- change 2: tiling -----------------------------------------------------------------


def test_without_max_tile_degrees_fetch_is_called_exactly_once(clean_registry):
    calls = []

    class UntiledAdapter(SourceAdapter):
        name = "untiled"
        source = Campsite.Source.RIDB
        model = Campsite

        def fetch(self, aoi):
            calls.append(aoi)
            return []

        def normalize(self, raw):
            return []

    clean_registry.register(UntiledAdapter)
    UntiledAdapter().run(ADK)

    assert len(calls) == 1
    assert calls[0] is ADK, "an untiled adapter should get the original object untouched"


def test_tiling_splits_the_area_into_tiles_that_cover_it_exactly(clean_registry):
    seen = []

    class TiledAdapter(SourceAdapter):
        name = "tiled"
        source = Campsite.Source.OSM
        model = Campsite
        max_tile_degrees = 1.0

        def fetch(self, aoi):
            seen.append(aoi)
            return []

        def normalize(self, raw):
            return []

    clean_registry.register(TiledAdapter)
    TiledAdapter().run(ADK)

    # 2.1 wide / 1.9 tall at 1.0 degrees -> 3 columns x 2 rows
    assert len(seen) == 6
    assert len({a.bbox for a in seen}) == 6, "tiles must be distinct"
    assert all(a.states == ADK.states for a in seen), "tiles inherit region metadata"

    union = seen[0].as_polygon()
    for area in seen[1:]:
        union = union.union(area.as_polygon())

    assert union.equals(ADK.as_polygon()), "tiles must cover the original with no gaps"


def test_a_feature_returned_by_two_tiles_is_written_once(clean_registry):
    """Also guards a real Postgres limit, not just a tidiness concern.

    Postgres rejects two rows with the same conflict target inside one
    INSERT ... ON CONFLICT ("cannot affect row a second time"). Without dedup the six
    copies below would land in a single batch and the run would fail outright.
    """

    class StraddlingAdapter(SourceAdapter):
        name = "straddling"
        source = Campsite.Source.OSM
        model = Campsite
        max_tile_degrees = 1.0

        def fetch(self, aoi):
            return [aoi]

        def normalize(self, raw):
            for _ in raw:
                yield {"source_id": "on-the-boundary", "geom": SOMEWHERE.clone()}

    clean_registry.register(StraddlingAdapter)
    run = StraddlingAdapter().run(ADK)

    assert Campsite.objects.filter(source_id="on-the-boundary").count() == 1
    assert run.record_count == 1, "a deduped feature must be counted once"
    assert run.status == IngestRun.Status.SUCCESS


def test_tiling_and_streaming_work_together(clean_registry):
    class TiledStreamAdapter(SourceAdapter):
        name = "tiled-stream"
        source = Campsite.Source.OSM
        model = Campsite
        max_tile_degrees = 1.0
        batch_size = 7

        def fetch(self, aoi):
            for i in range(5):
                yield (aoi.name, i)

        def normalize(self, raw):
            for name, i in raw:
                yield {"source_id": f"{name}-{i}", "geom": SOMEWHERE.clone()}

    clean_registry.register(TiledStreamAdapter)
    patcher, sizes = spy_on_bulk_create()

    with patcher:
        run = TiledStreamAdapter().run(ADK)

    # 6 tiles x 5 records, batched at 7: 7 + 7 + 7 + 7 + 2
    assert run.record_count == 30
    assert sizes == [7, 7, 7, 7, 2]
    assert Campsite.objects.count() == 30
    assert run.status == IngestRun.Status.SUCCESS


def test_tiles_are_not_built_when_the_area_already_fits(clean_registry):
    calls = []

    class BigTileAdapter(SourceAdapter):
        name = "big-tile"
        source = Campsite.Source.OSM
        model = Campsite
        max_tile_degrees = 50.0  # far larger than the region

        def fetch(self, aoi):
            calls.append(aoi)
            return []

        def normalize(self, raw):
            return []

    clean_registry.register(BigTileAdapter)
    BigTileAdapter().run(ADK)

    assert len(calls) == 1
    assert calls[0].bbox == ADK.bbox
