"""
Tests for the scoring engine (TM05-43).

Each factor is tested on its own against geometry placed at known distances, then the
combination and the edge cases the AC names: no water nearby, no trail nearby, unknown
legal status. The shipped config.yml is loaded once for the curve values, but every test
that depends on a weight builds its own config with `parse`, so tuning the real weights
never breaks a test.
"""

import copy
import json
from pathlib import Path

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon

from geodata.models import Campsite, PublicLand, Trail, WaterFeature
from scoring.config import ScoringConfigError, load, parse
from scoring.curves import peak_curve
from scoring.engine import ScoringError, score_campsite, score_location
from scoring.factors import LegalFactor, TrailFactor, WaterFactor

LON, LAT = -73.85, 44.18
M_PER_DEG_LAT = 111_120


def north(metres, lon=LON, lat=LAT):
    return Point(lon, lat + metres / M_PER_DEG_LAT, srid=4326)


FORECAST = json.loads((Path(__file__).parent / "fixtures" / "open_meteo_forecast.json").read_text())


@pytest.fixture(autouse=True)
def recorded_weather(monkeypatch):
    """Weather is a live factor; every test here answers it from a recorded response so
    no test touches the network. test_analysis.py covers the analysis itself."""
    calls = []

    def fake_fetch(url, params):
        calls.append(params)
        return copy.deepcopy(FORECAST)

    monkeypatch.setattr("analysis.analyses.weather.fetch_json", fake_fetch)
    return calls


class Terrain:
    """Stands in for 3DEP: elevation rises `grade` metres per metre northwards, so the
    slope at any site is atan(grade). Flat unless a test says otherwise."""

    grade = 0.0
    down = False

    def post(self, points):
        if self.down:
            from analysis.base import AnalysisError

            raise AnalysisError("3DEP down")
        return {
            "samples": [
                {
                    "locationId": i,
                    "value": str(500 + self.grade * (p.y - LAT) * M_PER_DEG_LAT),
                    "resolution": 1,
                    "attributes": {"Name": "TEST"},
                }
                for i, p in enumerate(points)
            ]
        }


@pytest.fixture(autouse=True)
def terrain(monkeypatch):
    """Slope is a live 3DEP factor (TM05-64); every test here answers it locally."""
    stub = Terrain()
    monkeypatch.setattr("analysis.analyses.elevation.post_samples", stub.post)
    return stub


def shipped():
    return load()


def raw_config(**weights):
    raw = {
        "model_version": "test",
        "weights": weights or dict(shipped().weights),
        "factors": copy.deepcopy(shipped().factors),
    }
    return raw


# --- curves (no database) ------------------------------------------------------------


class TestPeakCurve:
    params = {"ideal_m": 60, "at_zero": 35, "half_distance_m": 400}

    def test_peaks_at_the_ideal_distance(self):
        assert peak_curve(60, **self.params) == 100

    def test_on_the_bank_is_not_best(self):
        assert peak_curve(0, **self.params) == 35
        assert peak_curve(0, **self.params) < peak_curve(60, **self.params)

    def test_halves_every_half_distance_past_the_ideal(self):
        assert peak_curve(460, **self.params) == pytest.approx(50)
        assert peak_curve(860, **self.params) == pytest.approx(25)

    def test_falls_off_on_both_sides(self):
        below = [peak_curve(d, **self.params) for d in (0, 20, 40, 60)]
        above = [peak_curve(d, **self.params) for d in (60, 200, 800, 3000)]
        assert below == sorted(below)
        assert above == sorted(above, reverse=True)

    def test_rejects_negative_distance(self):
        with pytest.raises(ValueError):
            peak_curve(-1, **self.params)


# --- config (no database) ------------------------------------------------------------


class TestConfig:
    def test_shipped_config_loads_with_every_factor(self):
        config = shipped()
        assert set(config.weights) == {"water", "legal", "trail", "weather", "slope", "land_cover"}
        assert config.factor("water")["ideal_m"] == 60

    def test_capacity_is_not_a_factor(self):
        assert "capacity" not in shipped().weights

    def test_digest_changes_when_a_weight_changes(self):
        a = parse(raw_config(water=0.35, legal=0.3, trail=0.2))
        b = parse(raw_config(water=0.5, legal=0.3, trail=0.2))
        assert a.digest != b.digest
        assert parse(raw_config(water=0.35, legal=0.3, trail=0.2)).digest == a.digest

    @pytest.mark.parametrize(
        "raw",
        [
            [],
            {"weights": {"water": 1}},
            {"model_version": "x", "weights": {}},
            {"model_version": "x", "weights": {"water": -1}},
            {"model_version": "x", "weights": {"water": True}},
        ],
    )
    def test_invalid_config_is_rejected(self, raw):
        with pytest.raises(ScoringConfigError):
            parse(raw)


# --- factors and engine (database) ---------------------------------------------------


def water(distance_m, perennial=True, feature_type="stream", source_id=None):
    return WaterFeature.objects.create(
        source=WaterFeature.Source.NHD,
        source_id=source_id or f"w-{distance_m}-{perennial}-{feature_type}",
        name="Test Brook",
        geom=north(distance_m),
        feature_type=feature_type,
        perennial=perennial,
    )


def trail(distance_m, name="Test Trail"):
    lat = LAT + distance_m / M_PER_DEG_LAT
    return Trail.objects.create(
        source=Trail.Source.OSM,
        source_id=f"t-{distance_m}",
        name=name,
        geom=MultiLineString(LineString((LON - 0.01, lat), (LON + 0.01, lat)), srid=4326),
    )


def parcel(access, gap="1", source_id=None, designation="Test Wilderness"):
    ring = Polygon(
        (
            (LON - 0.01, LAT - 0.01),
            (LON + 0.01, LAT - 0.01),
            (LON + 0.01, LAT + 0.01),
            (LON - 0.01, LAT + 0.01),
            (LON - 0.01, LAT - 0.01),
        ),
        srid=4326,
    )
    return PublicLand.objects.create(
        source=PublicLand.Source.PADUS,
        source_id=source_id or f"p-{access}-{gap}",
        geom=MultiPolygon(ring, srid=4326),
        public_access=access,
        gap_status=gap,
        designation=designation,
    )


def factor_by_key(result, key):
    return next(f for f in result["factors"] if f["key"] == key)


@pytest.mark.django_db
@pytest.mark.integration
class TestWaterFactor:
    def evaluate(self):
        return WaterFactor(shipped().factor("water")).evaluate(LON, LAT)

    def test_ideal_distance_scores_near_100_and_reports_the_measurement(self):
        water(60)
        result = self.evaluate()
        assert result.status == "scored"
        assert result.score == pytest.approx(100, abs=2)
        assert result.measurement["distance_m"] == pytest.approx(60, rel=0.02)
        assert result.measurement["perennial"] is True
        assert "60 m" in result.explanation

    def test_bank_scores_lower_than_ideal(self):
        water(2)
        assert self.evaluate().score < 45

    def test_perennial_beats_nearer_intermittent(self):
        water(60, perennial=False)
        water(150, perennial=True)
        result = self.evaluate()
        assert result.measurement["perennial"] is True
        assert result.measurement["nearest_any_m"] == pytest.approx(60, rel=0.02)
        assert "scored lower" in result.explanation

    def test_intermittent_is_weighted_below_perennial(self):
        water(60, perennial=False)
        intermittent = self.evaluate().score
        WaterFeature.objects.all().delete()
        water(60, perennial=True)
        assert intermittent < self.evaluate().score

    def test_unknown_flow_sits_between(self):
        water(60, perennial=None)
        assert 55 < self.evaluate().score < 100

    def test_wetland_counts_for_less_than_a_stream(self):
        water(60, feature_type="wetland")
        assert self.evaluate().score == pytest.approx(50, abs=2)

    def test_no_water_nearby_is_no_data_and_scores_zero(self):
        water(5000)  # beyond max_search_m
        result = self.evaluate()
        assert result.status == "no_data"
        assert result.score == 0
        assert result.measurement["distance_m"] is None


@pytest.mark.django_db
@pytest.mark.integration
class TestTrailFactor:
    def evaluate(self):
        return TrailFactor(shipped().factor("trail")).evaluate(LON, LAT)

    def test_curve_peaks_near_the_trail_not_on_it(self):
        trail(60)
        near = self.evaluate().score
        Trail.objects.all().delete()
        trail(0)
        on = self.evaluate().score
        assert near == pytest.approx(100, abs=2)
        assert on == pytest.approx(50, abs=2)

    def test_reports_name_and_distance(self):
        trail(400, name="Van Hoevenberg Trail")
        result = self.evaluate()
        assert result.measurement["name"] == "Van Hoevenberg Trail"
        assert result.measurement["distance_m"] == pytest.approx(400, rel=0.02)
        assert result.explanation.startswith("Van Hoevenberg Trail is 4")
        assert "m away" in result.explanation

    def test_no_trail_nearby_is_no_data(self):
        result = self.evaluate()
        assert result.status == "no_data"
        assert result.score == 0


@pytest.mark.django_db
@pytest.mark.integration
class TestLegalFactor:
    def evaluate(self):
        return LegalFactor(shipped().factor("legal")).evaluate(LON, LAT)

    def test_open_gap1_land_scores_full(self):
        parcel("open", "1")
        result = self.evaluate()
        assert result.score == 100
        assert result.measurement["public_access"] == "open"
        assert result.caps == []

    def test_gap_status_modulates_the_score(self):
        parcel("open", "4")
        assert self.evaluate().score == pytest.approx(75)

    def test_closed_land_scores_zero_and_caps_the_total(self):
        parcel("closed", "2")
        result = self.evaluate()
        assert result.score == 0
        assert result.caps[0]["max_score"] == 0
        assert "closed" in result.caps[0]["reason"]

    def test_overlapping_parcels_use_the_most_restrictive_access(self):
        parcel("open", "1", source_id="a")
        parcel("closed", "1", source_id="b")
        assert self.evaluate().measurement["public_access"] == "closed"

    def test_unknown_access_is_scored_low_not_excluded(self):
        parcel("unknown", "")
        result = self.evaluate()
        assert result.status == "scored"
        assert result.score == pytest.approx(40 * 0.85)
        assert "unknown" in result.explanation

    def test_outside_public_land_is_no_data_with_a_low_score(self):
        result = self.evaluate()
        assert result.status == "no_data"
        assert result.score == 15
        assert result.measurement["parcels"] == 0


@pytest.mark.django_db
@pytest.mark.integration
class TestEngine:
    def test_scores_a_location_from_coordinates_with_the_full_contract(self):
        water(60)
        trail(60)
        parcel("open", "1")
        result = score_location(LON, LAT)

        assert set(result) == {
            "contract",
            "model_version",
            "config_digest",
            "location",
            "score",
            "factors",
            "caps",
        }
        assert result["contract"] == 1
        assert [f["key"] for f in result["factors"]] == list(shipped().weights)
        weather = factor_by_key(result, "weather")
        assert weather["status"] == "scored"
        # Perfect water, trail and legal; the recorded forecast is a rainy day.
        assert 80 < result["score"] < 100
        for factor in result["factors"]:
            assert set(factor) == {
                "key",
                "label",
                "status",
                "score",
                "weight",
                "effective_weight",
                "contribution",
                "measurement",
                "explanation",
            }

    def test_placeholders_are_excluded_and_weights_renormalised(self):
        water(60)
        result = score_location(LON, LAT)
        land_cover = factor_by_key(result, "land_cover")
        assert land_cover["status"] == "not_available"
        assert land_cover["score"] is None
        assert land_cover["effective_weight"] == 0
        counted = [f for f in result["factors"] if f["status"] != "not_available"]
        assert sum(f["effective_weight"] for f in counted) == pytest.approx(1, abs=1e-3)

    def test_contributions_add_up_to_the_score(self):
        water(300)
        trail(900)
        parcel("open", "3")
        result = score_location(LON, LAT)
        total = sum(f["contribution"] for f in result["factors"])
        assert total == pytest.approx(result["score"], abs=0.6)

    def test_combined_score_is_the_weighted_mean(self):
        water(60)  # ~100
        parcel("open", "4")  # 75
        # no trail: 0
        config = parse(raw_config(water=1, legal=1, trail=2))
        result = score_location(LON, LAT, config)
        water_score = factor_by_key(result, "water")["score"]
        assert result["score"] == round((water_score + 75 + 0) / 4)

    def test_weights_are_tuned_in_config_without_code_changes(self):
        water(60)
        heavy = score_location(LON, LAT, parse(raw_config(water=10, legal=1, trail=1)))
        light = score_location(LON, LAT, parse(raw_config(water=1, legal=10, trail=10)))
        assert heavy["score"] > light["score"]
        assert heavy["config_digest"] != light["config_digest"]

    def test_closed_land_caps_an_otherwise_good_site(self):
        water(60)
        trail(60)
        parcel("closed", "1")
        result = score_location(LON, LAT)
        assert result["score"] == 0
        assert result["caps"][0]["factor"] == "legal"
        assert factor_by_key(result, "water")["score"] > 90

    def test_nothing_nearby_and_unknown_legal_status(self):
        """All three AC edge cases at once: no water, no trail, not on public land."""
        result = score_location(LON, LAT)
        assert factor_by_key(result, "water")["status"] == "no_data"
        assert factor_by_key(result, "trail")["status"] == "no_data"
        assert factor_by_key(result, "legal")["status"] == "no_data"
        weights = shipped().weights
        weather = factor_by_key(result, "weather")["score"]
        counted = ("water", "legal", "trail", "weather", "slope")
        # The stub terrain is flat, so slope scores 100.
        expected = (
            15 * weights["legal"] + weather * weights["weather"] + 100 * weights["slope"]
        ) / sum(weights[key] for key in counted)
        assert result["score"] == round(expected)

    def test_capacity_does_not_change_a_campsite_score(self):
        water(60)
        small = Campsite.objects.create(
            source=Campsite.Source.RIDB, source_id="c1", geom=Point(LON, LAT, srid=4326), capacity=2
        )
        large = Campsite.objects.create(
            source=Campsite.Source.RIDB,
            source_id="c2",
            geom=Point(LON, LAT, srid=4326),
            capacity=40,
        )
        a, b = score_campsite(small), score_campsite(large)
        # Compare scores, not whole results: the second call's weather is a cache hit, so
        # its measurement says cached: true.
        assert a["score"] == b["score"]
        assert [f["score"] for f in a["factors"]] == [f["score"] for f in b["factors"]]

    @pytest.mark.parametrize("lon, lat", [(200, 44), (-73, 95)])
    def test_invalid_coordinates_are_rejected(self, lon, lat):
        with pytest.raises(ScoringError):
            score_location(lon, lat)

    def test_unknown_factor_in_config_is_rejected(self):
        with pytest.raises(ScoringConfigError):
            score_location(LON, LAT, parse(raw_config(water=1, altitude=1)))


@pytest.mark.django_db
@pytest.mark.integration
class TestWeatherFactor:
    def evaluate(self):
        from scoring.factors import WeatherFactor

        return WeatherFactor(shipped().factor("weather")).evaluate(LON, LAT)

    def test_scores_the_forecast_day_with_explained_penalties(self):
        result = self.evaluate()
        day = FORECAST["daily"]
        rain, wind = day["precipitation_sum"][0], day["wind_speed_10m_max"][0]
        settings = shipped().factor("weather")
        expected = 100 - min(40, rain * 4) - min(30, max(0, wind - 25))
        assert result.status == "scored"
        assert result.score == pytest.approx(expected)
        assert result.measurement["date"] == day["time"][0]
        assert result.measurement["precipitation_mm"] == rain
        assert settings["precipitation_penalty_per_mm"] == 4
        assert "mm of rain" in result.explanation

    def test_second_call_is_served_from_the_cache(self, recorded_weather):
        assert self.evaluate().measurement["cached"] is False
        assert self.evaluate().measurement["cached"] is True
        assert len(recorded_weather) == 1

    def test_frost_is_penalised(self, monkeypatch):
        frosty = copy.deepcopy(FORECAST)
        frosty["daily"]["temperature_2m_min"][0] = -5
        frosty["daily"]["precipitation_sum"][0] = 0
        frosty["daily"]["wind_speed_10m_max"][0] = 10
        monkeypatch.setattr("analysis.analyses.weather.fetch_json", lambda url, params: frosty)
        result = self.evaluate()
        assert result.score == pytest.approx(85)
        assert result.measurement["penalties"]["freezing"] == 15

    def test_unreachable_source_is_not_available_and_excluded(self, monkeypatch):
        from analysis.base import AnalysisError

        def down(url, params):
            raise AnalysisError("down")

        monkeypatch.setattr("analysis.analyses.weather.fetch_json", down)
        result = score_location(LON, LAT)
        weather = factor_by_key(result, "weather")
        assert weather["status"] == "not_available"
        assert weather["score"] is None
        assert weather["effective_weight"] == 0


class TestSlopeCurve:
    curve = [[0, 100], [3, 100], [8, 50], [15, 10], [20, 0]]

    def test_flat_ground_is_ideal(self):
        from scoring.factors import piecewise

        assert piecewise(0, self.curve) == 100
        assert piecewise(3, self.curve) == 100

    def test_interpolates_between_points_and_clamps(self):
        from scoring.factors import piecewise

        assert piecewise(5.5, self.curve) == pytest.approx(75)
        assert piecewise(15, self.curve) == 10
        assert piecewise(40, self.curve) == 0

    def test_steeper_never_scores_higher(self):
        from scoring.factors import piecewise

        scores = [piecewise(d, self.curve) for d in range(0, 30)]
        assert scores == sorted(scores, reverse=True)


@pytest.mark.django_db
@pytest.mark.integration
class TestSlopeFactor:
    def evaluate(self):
        from scoring.factors import SlopeFactor

        return SlopeFactor(shipped().factor("slope")).evaluate(LON, LAT)

    def test_flat_ground_scores_full_with_its_measurement(self, terrain):
        result = self.evaluate()
        assert result.status == "scored"
        assert result.score == 100
        assert result.measurement["slope_deg"] == pytest.approx(0, abs=0.01)
        assert result.measurement["elevation_m"] == pytest.approx(500, abs=0.5)
        assert "flat" in result.explanation

    def test_a_ten_percent_grade_scores_on_the_curve(self, terrain):
        terrain.grade = 0.10  # 5.71 degrees
        result = self.evaluate()
        assert result.measurement["slope_pct"] == pytest.approx(10, abs=0.2)
        assert result.measurement["slope_deg"] == pytest.approx(5.71, abs=0.05)
        assert result.score == pytest.approx(100 - (5.71 - 3) / 5 * 50, abs=0.5)

    def test_a_hillside_scores_zero(self, terrain):
        terrain.grade = 0.5  # 26.6 degrees
        assert self.evaluate().score == 0

    def test_unreachable_3dep_is_not_available_and_excluded(self, terrain):
        terrain.down = True
        water(60)
        result = score_location(LON, LAT)
        slope = factor_by_key(result, "slope")
        assert slope["status"] == "not_available"
        assert slope["effective_weight"] == 0
