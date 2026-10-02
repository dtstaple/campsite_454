"""
Tests for route elevation profiles (TM05-59): stitching, sampling, gap filling, gain and
loss with noise, max grade, and the analysis end to end with 3DEP stubbed out. Geometry
is built in EPSG:5070 metres where distances matter, so expected values are exact.
"""

import math

import pytest
from django.contrib.gis.geos import LineString, MultiLineString

from analysis.analyses import elevation
from analysis.analyses.elevation import (
    RouteProfile,
    fetch_elevations,
    fill_gaps,
    gain_loss,
    max_grade,
    naive_gain_loss,
    profile_stats,
    sample_points,
    smooth,
    stitch,
)
from analysis.base import AnalysisError
from analysis.models import AnalysisResult

# Somewhere near the High Peaks, in EPSG:5070 metres.
X0, Y0 = 1_770_000.0, 2_550_000.0


def m_line(*coords):
    return LineString([(X0 + x, Y0 + y) for x, y in coords], srid=5070)


def to_4326(geom):
    return geom.transform(4326, clone=True)


# --- stitching -----------------------------------------------------------------------


class TestStitch:
    def test_touching_members_out_of_order_and_reversed_become_one_line(self):
        a = m_line((0, 0), (1000, 0))
        b = m_line((2000, 0), (1000, 0))  # reversed, and listed after c
        c = m_line((2000, 0), (3000, 0))
        route = to_4326(MultiLineString(a, c, b, srid=5070))

        line, info = stitch(route)

        assert line.length == pytest.approx(3000, rel=1e-3)
        assert info["parts_used"] == info["parts"]
        assert info["parts_left_out"] == 0

    def test_small_gaps_are_joined(self):
        a = m_line((0, 0), (1000, 0))
        b = m_line((1030, 0), (2000, 0))  # 30 m gap, under the 50 m tolerance
        line, info = stitch(to_4326(MultiLineString(a, b, srid=5070)))
        assert info["parts_left_out"] == 0
        assert info["largest_join_gap_m"] == pytest.approx(30, abs=0.5)
        assert line.length == pytest.approx(2000, rel=1e-3)

    def test_a_parallel_bypass_is_left_out_not_jumped_to(self):
        main = m_line((0, 0), (3000, 0))
        bypass = m_line((1000, 0), (1500, 300), (2000, 0))  # meets the middle
        line, info = stitch(to_4326(MultiLineString(main, bypass, srid=5070)))

        assert info["parts_left_out"] == 1
        assert info["left_out_m"] > 1000
        assert line.length == pytest.approx(3000, rel=1e-3)

    def test_a_far_stub_is_left_out(self):
        main = m_line((0, 0), (3000, 0))
        stub = m_line((5000, 5000), (5100, 5000))
        _, info = stitch(to_4326(MultiLineString(main, stub, srid=5070)))
        assert info["parts_left_out"] == 1


# --- sampling and series maths (no database) -----------------------------------------


class TestSampling:
    def test_points_every_spacing_plus_the_end(self):
        distances, points = sample_points(m_line((0, 0), (1010, 0)), 25)
        assert distances[:3] == [0, 25, 50]
        assert distances[-1] == pytest.approx(1010)
        assert all(p.srid == 4326 for p in points)

    def test_a_tiny_remainder_does_not_add_a_near_duplicate_end(self):
        distances, _ = sample_points(m_line((0, 0), (1002, 0)), 25)
        assert distances[-1] == 1000


class TestSeries:
    def test_fill_gaps_interpolates_and_extends_ends(self):
        assert fill_gaps([None, 10, None, None, 40, None]) == [10, 10, 20, 30, 40, 40]

    def test_fill_gaps_with_no_data_at_all_is_an_error(self):
        with pytest.raises(AnalysisError):
            fill_gaps([None, None])

    def test_smooth_is_a_centred_moving_average(self):
        assert smooth([0, 0, 9, 0, 0], 3) == [0, 3, 3, 3, 0]

    def test_noise_on_a_steady_climb_is_not_counted_as_gain(self):
        """A 300 m climb with +/-1.5 m of sample-to-sample jitter: a naive sum counts
        every wobble; smoothing plus a threshold recovers the real climb."""
        clean = [i * 1.5 for i in range(201)]  # 0 -> 300 m
        noisy = [v + (1.5 if i % 2 else -1.5) for i, v in enumerate(clean)]

        naive_gain, _ = naive_gain_loss(noisy)
        gain, loss = gain_loss(smooth(noisy, 5), 3)

        assert naive_gain == pytest.approx(450)  # half again too much
        assert gain == pytest.approx(300, abs=10)
        assert loss < 5

    def test_real_descents_are_counted(self):
        values = [0, 50, 100, 60, 20, 80, 120]
        gain, loss = gain_loss(values, 3)
        assert gain == pytest.approx(200)
        assert loss == pytest.approx(80)

    def test_changes_under_the_threshold_are_ignored(self):
        assert gain_loss([0, 2, 0, 2, 0, 2], 3) == (0, 0)

    def test_max_grade_is_measured_over_the_window_not_one_step(self):
        distances = [i * 25.0 for i in range(41)]  # 1 km
        values = [0.0] * 41
        values[20] = 4.0  # one spike: 16% between neighbours, 4% over 100 m
        for i in range(30, 41):  # a real 10% grade over the last 250 m
            values[i] = (i - 30) * 2.5
        grade, at = max_grade(distances, values, 100)
        assert grade == pytest.approx(10, abs=0.5)
        assert at >= 700

    def test_profile_stats_reports_everything_the_panel_needs(self):
        distances = [i * 25.0 for i in range(81)]
        values = [500 + 300 * math.sin(math.pi * d / 2000) for d in distances]
        stats = profile_stats(
            distances,
            values,
            {"spacing_m": 25, "smoothing_window_m": 100, "threshold_m": 3, "grade_window_m": 100},
        )
        assert stats["length_m"] == 2000
        assert stats["gain_m"] == pytest.approx(300, abs=15)
        # Up and back down a half sine: 300 m each way.
        assert stats["loss_m"] == pytest.approx(300, abs=15)
        assert stats["high_m"] == pytest.approx(800, abs=5)
        assert stats["high_at_m"] == pytest.approx(1000, abs=50)
        assert set(stats) >= {"loss_m", "low_m", "max_grade_pct", "naive_gain_m"}


# --- 3DEP mapping and the analysis (database) -----------------------------------------


def fake_post(elevation_for):
    """A post_samples stand-in answering in shuffled order, like the real service."""

    def post(points):
        samples = [
            {
                "locationId": i,
                "value": "NoData" if elevation_for(p) is None else str(elevation_for(p)),
                "resolution": 1,
                "attributes": {"Name": "TEST_LIDAR", "VerticalDatum": "NAVD 88"},
            }
            for i, p in enumerate(points)
        ]
        return {"samples": samples[::-1]}

    return post


class TestFetch:
    def test_out_of_order_samples_and_batches_map_back_to_points(self, monkeypatch):
        monkeypatch.setattr(elevation, "BATCH_SIZE", 7)
        _, points = sample_points(m_line((0, 0), (500, 0)), 25)
        monkeypatch.setattr(elevation, "post_samples", fake_post(lambda p: round(p.x, 6)))

        values, source = fetch_elevations(points)

        assert values == [round(p.x, 6) for p in points]
        assert source["datasets"] == ["TEST_LIDAR"]
        assert source["resolution_m"] == [1]

    def test_nodata_becomes_none(self, monkeypatch):
        _, points = sample_points(m_line((0, 0), (100, 0)), 25)
        monkeypatch.setattr(elevation, "post_samples", fake_post(lambda p: None))
        values, _ = fetch_elevations(points)
        assert values == [None] * len(points)


@pytest.mark.django_db
@pytest.mark.integration
class TestRouteProfile:
    def route(self):
        a = m_line((0, 0), (1000, 0))
        b = m_line((1000, 0), (2000, 0))
        return to_4326(MultiLineString(a, b, srid=5070))

    def test_computes_stores_and_then_serves_from_cache(self, monkeypatch):
        calls = []

        def post(points):
            calls.append(len(points))
            return fake_post(lambda p: 100.0)(points)

        monkeypatch.setattr(elevation, "post_samples", post)
        first = RouteProfile().run(self.route())
        second = RouteProfile().run(self.route())

        assert first.cached is False and second.cached is True
        assert len(calls) == 1
        value = first.value
        assert len(value["distance_m"]) == len(value["elevation_m"]) == 81
        assert value["stats"]["length_m"] == pytest.approx(2000, rel=1e-3)
        assert value["stats"]["gain_m"] == 0
        assert len(value["line"]) >= 2
        assert first.provenance["source"] == "usgs-3dep"
        assert first.provenance["sample_count"] == 81
        assert first.provenance["nodata_count"] == 0
        row = AnalysisResult.objects.get(key=first.key)
        assert row.analysis == "route_profile"
        # A year: terrain does not change.
        assert (row.expires_at - row.computed_at).days == 365

    def test_long_routes_are_sampled_more_coarsely(self, monkeypatch):
        monkeypatch.setattr(elevation, "MAX_SAMPLES", 40)
        monkeypatch.setattr(elevation, "post_samples", fake_post(lambda p: 100.0))
        value = RouteProfile().run(self.route()).value  # 2 km
        assert len(value["distance_m"]) <= 41
        assert value["params"]["spacing_m"] == pytest.approx(50, rel=1e-3)

    def test_a_3dep_failure_is_not_cached(self, monkeypatch):
        def down(points):
            raise AnalysisError("3DEP down")

        monkeypatch.setattr(elevation, "post_samples", down)
        with pytest.raises(AnalysisError):
            RouteProfile().run(self.route())
        assert not AnalysisResult.objects.filter(analysis="route_profile").exists()
