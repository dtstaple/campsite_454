"""
Does the data in the database make sense together?

Every other test checks that code behaves given fixture input. None of them notice when
the data itself is incoherent, and this project has shipped exactly that with a green
suite: no region held all four layers, campsites and water were in different states, and
about a third of "trails" were sidewalks. These checks look at the actual rows.

They run against whatever DATABASE_URL points at -- the seeded sample or a full ingest --
and are deselected from the normal run. From the repo root:

    pytest -m data

A region here is an ingest region, taken from IngestRun: its name and the bbox recorded in
the run's parameters. That makes the checks work unchanged on the committed sample (one
small region) and on the full Northeast database.

Distances: geometry is stored in EPSG:4326, so ST_Distance on the stored columns returns
degrees, and a degree of longitude is ~80 km in the Adirondacks against ~111 km of
latitude. Proximity is therefore measured in metres with a geography cast
(ST_DWithin(a::geography, b::geography, metres)), which is exact on the spheroid. A cast
cannot use the geometry GiST index, so each lookup is first narrowed with an index-backed
`&&` against the campsite expanded by the same distance converted to degrees at that
latitude -- a deliberately generous box, so the prefilter never excludes a real match and
the geography test alone decides.

Every failure message says what is wrong with the data and where to look, because
"assert 0 > 0" at 2am tells you nothing.
"""

import json

import pytest
from django.db import connection

from geodata.models import Campsite, IngestRun, PublicLand, Trail, WaterFeature

pytestmark = [pytest.mark.data, pytest.mark.django_db]

LAYERS = {
    "public land parcels": PublicLand,
    "trails": Trail,
    "water features": WaterFeature,
    "campsites": Campsite,
}

# A backcountry site is chosen for its water and reached by a trail, so most sites should
# have both within a kilometre. Not all: a drive-in campground can sit by a road with
# neither mapped nearby, hence a share rather than every site. Data from two different
# places scores near 0%, far below this.
NEAR_M = 1000
MIN_SHARE_NEAR = 0.75

# Adapters ask each source for features intersecting the region's bbox, so a feature may
# extend past the edge but should touch the box. The tolerance (~1 km) allows for a
# campsite mapped as an area, which is stored at its centre and can fall just outside a
# box the area itself intersects.
EDGE_TOLERANCE_DEG = 0.01

# What urban pedestrian infrastructure looks like in OSM tags. Written out here rather than
# imported from the osm_trails adapter on purpose: this checks the adapter's output, so it
# must not share the adapter's definition and the adapter's mistakes.
HIKING_HIGHWAY_VALUES = ("path", "footway", "track", "bridleway")
URBAN_FOOTWAY_VALUES = ("sidewalk", "crossing", "traffic_island", "access_aisle")
MAX_URBAN_SHARE = 0.01

EXAMPLES = 3


def _table(model) -> str:
    return connection.ops.quote_name(model._meta.db_table)


def _query(sql: str, params=()) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "n/a"


@pytest.fixture(scope="module")
def regions(django_db_blocker) -> dict[str, tuple[float, float, float, float]]:
    """{region name: bbox} for every region an ingest run recorded a bbox for."""
    with django_db_blocker.unblock():
        rows = _query(
            f"""
            SELECT DISTINCT ON (region) region, parameters -> 'bbox'
            FROM {_table(IngestRun)}
            WHERE jsonb_typeof(parameters -> 'bbox') = 'array'
            ORDER BY region, started_at DESC
            """
        )
        features = sum(model.objects.count() for model in LAYERS.values())

    if not features:
        pytest.fail(
            "The database has no features at all, so there is nothing to check. Seed it "
            "(`cd backend && python manage.py seed`) or run an ingest first, and check "
            "DATABASE_URL points where you think it does."
        )
    if not rows:
        pytest.fail(
            f"The database has {features:,} features but no ingest run records a bbox, so "
            "there are no regions to check against. Were rows loaded without the pipeline?"
        )
    # A raw cursor hands jsonb back as text.
    return {name: tuple(float(v) for v in json.loads(bbox)) for name, bbox in rows}


# --- one region has everything ---------------------------------------------------------


def test_some_region_has_every_layer(regions):
    counts: dict[str, dict[str, int]] = {}
    for name, bbox in regions.items():
        counts[name] = {
            label: _query(
                f"""
                SELECT count(*) FROM {_table(model)}
                WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                  AND ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
                """,
                (*bbox, *bbox),
            )[0][0]
            for label, model in LAYERS.items()
        }

    complete = [name for name, layers in counts.items() if all(layers.values())]
    if complete:
        return

    lines = []
    for name, layers in sorted(counts.items()):
        empty = [label for label, n in layers.items() if not n]
        present = ", ".join(f"{n:,} {label}" for label, n in layers.items() if n) or "nothing"
        lines.append(f"  region {name} has 0 {' and 0 '.join(empty)} but {present}")
    pytest.fail(
        "No region contains all four layers, so no viewport can show a campsite with its "
        "water, trails and legal status together:\n"
        + "\n".join(lines)
        + "\nDid an ingest fail, or run for a different region than the others?"
    )


# --- campsites sit near water and trails -----------------------------------------------


def test_campsites_have_water_and_trails_nearby(regions):
    rows = _query(
        f"""
        SELECT coalesce(r.region, '(no ingest run)'), c.source_id, c.name,
               ST_X(c.geom), ST_Y(c.geom),
               EXISTS (
                   SELECT 1 FROM {_table(WaterFeature)} w
                   WHERE w.geom && box.search
                     AND ST_DWithin(w.geom::geography, c.geom::geography, %(m)s)
               ),
               EXISTS (
                   SELECT 1 FROM {_table(Trail)} t
                   WHERE t.geom && box.search
                     AND ST_DWithin(t.geom::geography, c.geom::geography, %(m)s)
               )
        FROM {_table(Campsite)} c
        LEFT JOIN {_table(IngestRun)} r ON r.id = c.last_run_id
        -- The search distance in degrees: longitude degrees shrink with cos(latitude), so
        -- dividing by it makes the box wide enough; 1.1 adds margin for the spheroid.
        CROSS JOIN LATERAL (
            SELECT ST_Expand(
                c.geom,
                1.1 * %(m)s / (111320 * cos(radians(ST_Y(c.geom)))),
                1.1 * %(m)s / 110574
            ) AS search
        ) box
        """,
        {"m": NEAR_M},
    )
    if not rows:
        pytest.fail(
            "There are no campsites in the database, so nothing can be near water or a "
            "trail. Did the osm-campsites (or ridb) ingest run?"
        )

    by_region: dict[str, list[tuple]] = {}
    for region, *rest in rows:
        by_region.setdefault(region, []).append(tuple(rest))

    problems = []
    for region, sites in sorted(by_region.items()):
        for index, what in ((4, "water"), (5, "a trail")):
            near = sum(1 for site in sites if site[index])
            if near / len(sites) >= MIN_SHARE_NEAR:
                continue
            far = [site for site in sites if not site[index]][:EXAMPLES]
            examples = "; ".join(
                f"{sid} {name!r} at {lon:.4f},{lat:.4f}"
                if name
                else f"{sid} at {lon:.4f},{lat:.4f}"
                for sid, name, lon, lat, *_ in far
            )
            problems.append(
                f"  region {region}: only {near:,} of {len(sites):,} campsites "
                f"({_pct(near, len(sites))}) have {what} within {NEAR_M:,} m "
                f"(need {MIN_SHARE_NEAR:.0%}), e.g. {examples}"
            )

    assert not problems, (
        "Campsites are not near the water and trails they should be near:\n"
        + "\n".join(problems)
        + "\nUsually the campsite ingest and the water/trail ingests covered different "
        "areas, or one of them is missing for this region."
    )


# --- features are where they were ingested for -----------------------------------------


def test_features_lie_inside_their_ingest_region(regions):
    problems = []
    for label, model in LAYERS.items():
        rows = _query(
            f"""
            SELECT r.region, count(*),
                   (array_agg(f.source_id ORDER BY f.id))[1:%(n)s],
                   (array_agg(ST_AsText(ST_PointOnSurface(f.geom), 3) ORDER BY f.id))[1:%(n)s]
            FROM {_table(model)} f
            JOIN {_table(IngestRun)} r ON r.id = f.last_run_id
            WHERE jsonb_typeof(r.parameters -> 'bbox') = 'array'
              AND NOT ST_Intersects(
                  f.geom,
                  ST_Expand(
                      ST_MakeEnvelope(
                          (r.parameters -> 'bbox' ->> 0)::float,
                          (r.parameters -> 'bbox' ->> 1)::float,
                          (r.parameters -> 'bbox' ->> 2)::float,
                          (r.parameters -> 'bbox' ->> 3)::float,
                          4326
                      ),
                      %(tol)s
                  )
              )
            GROUP BY r.region
            """,
            {"n": EXAMPLES, "tol": EDGE_TOLERANCE_DEG},
        )
        for region, count, ids, points in rows:
            bbox = list(regions.get(region, ()))
            examples = "; ".join(f"{sid} at {pt}" for sid, pt in zip(ids, points, strict=True))
            problems.append(
                f"  {count:,} {label} ingested for region {region} lie entirely outside its "
                f"bbox {bbox} (e.g. {examples})"
            )

    assert not problems, (
        "Features are stored against a region they are nowhere near:\n"
        + "\n".join(problems)
        + "\nAn adapter queried the wrong area, swapped lat/lon, or reprojected from the "
        "wrong source SRID."
    )


# --- trails are hiking trails ----------------------------------------------------------


def test_trails_look_like_hiking_trails(regions):
    rows = _query(
        f"""
        SELECT coalesce(r.region, '(no ingest run)'),
               count(*),
               count(*) FILTER (WHERE NOT (t.trail_type = ANY(%(hiking)s))),
               count(*) FILTER (WHERE t.raw -> 'tags' ->> 'footway' = ANY(%(urban)s)),
               count(*) FILTER (WHERE t.raw -> 'tags' ? 'golf'),
               (array_agg(t.source_id || ' ' || t.trail_type
                          || coalesce(' footway=' || (t.raw -> 'tags' ->> 'footway'), '')
                          || coalesce(' ' || quote_literal(nullif(t.name, '')), '')
                          ORDER BY t.id)
                FILTER (WHERE NOT (t.trail_type = ANY(%(hiking)s))
                           OR t.raw -> 'tags' ->> 'footway' = ANY(%(urban)s)
                           OR t.raw -> 'tags' ? 'golf'))[1:%(n)s]
        FROM {_table(Trail)} t
        LEFT JOIN {_table(IngestRun)} r ON r.id = t.last_run_id
        GROUP BY 1
        """,
        {
            "hiking": list(HIKING_HIGHWAY_VALUES),
            "urban": list(URBAN_FOOTWAY_VALUES),
            "n": EXAMPLES,
        },
    )
    if not rows:
        pytest.fail("There are no trails in the database. Did the osm-trails ingest run?")

    problems = []
    for region, total, not_path, urban, golf, examples in sorted(rows):
        # A row can be counted under two reasons; the share is an upper bound, which is
        # fine for a threshold this far below the failure it exists to catch.
        bad = min(total, not_path + urban + golf)
        if bad / total <= MAX_URBAN_SHARE:
            continue
        reasons = ", ".join(
            f"{n:,} {why}"
            for n, why in (
                (urban, f"sidewalks or crossings (footway={'/'.join(URBAN_FOOTWAY_VALUES)})"),
                (golf, "golf cart paths"),
                (not_path, f"not a path type at all (not {'/'.join(HIKING_HIGHWAY_VALUES)})"),
            )
            if n
        )
        problems.append(
            f"  region {region}: {bad:,} of {total:,} trails ({_pct(bad, total)}) look like "
            f"urban paths, not hiking trails -- {reasons}. "
            f"E.g. {'; '.join(examples or [])}"
        )

    assert not problems, (
        f"More than {MAX_URBAN_SHARE:.0%} of trails are urban infrastructure:\n"
        + "\n".join(problems)
        + "\nThe osm-trails filter was bypassed or these rows predate it. Re-running the "
        "ingest will not remove them (it upserts, it never deletes), so delete the region's "
        "trails and re-ingest."
    )
