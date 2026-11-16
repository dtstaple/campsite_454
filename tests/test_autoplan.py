"""
Auto-planned overnight stops (TM05-169): the choice of stops (pure), and the endpoint.

The pure tests give `solve()` stops at known places along a route of known length, so
the right answer is known exactly. The API tests use a straight 30 km line in EPSG:5070
with 3DEP stubbed, and set each campsite's legality verdict by id.
"""

import random

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point
from test_plans import client_for

from analysis.analyses import elevation
from geodata.models import Campsite, TrailRoute
from planning import plans
from planning.autoplan import (
    AutoPlanError,
    Climb,
    Option,
    days_for_target,
    load_settings,
    parse_settings,
    resolve_nights,
    solve,
)

SETTINGS = load_settings()
KM = 1000.0


def option(id, km, permitted=True, score=80, name=None):
    return Option(
        id=id,
        along_m=km * KM,
        permitted=permitted,
        score=score,
        name=name or id,
        verdict_label="Permitted · designated site" if permitted else "Unknown: check rules",
    )


def ids(solved):
    return [choice["id"] for choice in solved["choices"]]


# --- the method (pure) -------------------------------------------------------------------


def test_even_splits_take_the_stops_at_the_even_places():
    options = [
        option("a", 8.5),
        option("b", 10),
        option("c", 11.5),
        option("d", 18.5),
        option("e", 20),
        option("f", 21.5),
    ]
    solved = solve(30 * KM, options, 2, SETTINGS)
    assert ids(solved) == ["b", "e"]
    assert solved["day_target_m"] == 10 * KM
    assert solved["gaps"] == []
    assert solved["cost"] == pytest.approx(2 * SETTINGS.w_score * 0.2)


def test_a_night_with_no_legal_stop_is_reported_and_never_filled():
    options = [option("legal", 10), option("unverified", 20, permitted=False, score=99)]
    solved = solve(30 * KM, options, 2, SETTINGS)
    assert ids(solved) == ["legal"]
    (gap,) = solved["gaps"]
    assert gap["night"] == 2
    assert gap["unverified"] == 1
    # Night 2's window: 20 km +/- 0.3 of a 10 km day, so 17 to 23 km.
    assert (gap["from_m"], gap["to_m"]) == (17 * KM, 23 * KM)
    assert gap["message"].startswith(
        "No legal stop between mi 10.6 and mi 14.3 for night 2, so that night is left out"
    )
    assert "add one with + Night only after checking it yourself" in gap["message"]


def test_no_legal_stop_anywhere_chooses_nothing():
    solved = solve(30 * KM, [option("x", 10, permitted=False)], 2, SETTINGS)
    assert ids(solved) == [] and [g["night"] for g in solved["gaps"]] == [1, 2]


def test_a_stop_outside_every_window_is_never_chosen():
    """Within 30% of an even day either side: a stop at 5 km is not night 1 of a 10 km day."""
    solved = solve(30 * KM, [option("early", 5), option("b", 20)], 2, SETTINGS)
    assert ids(solved) == ["b"]
    assert [g["night"] for g in solved["gaps"]] == [1]


def test_a_higher_score_wins_when_the_days_are_as_even():
    options = [option("low", 9.5, score=60), option("high", 10.5, score=90)]
    solved = solve(20 * KM, options, 1, SETTINGS)
    assert ids(solved) == ["high"]
    assert solved["choices"][0]["reason"].startswith(
        "Score 90: the highest-scoring of 2 legal stops"
    )


def test_balance_beats_a_slightly_higher_score_and_says_so():
    options = [option("even", 10, score=80), option("lopsided", 12.8, score=85, name="Ridge")]
    solved = solve(20 * KM, options, 1, SETTINGS)
    (choice,) = solved["choices"]
    assert choice["id"] == "even"
    assert choice["alternative"]["id"] == "lopsided"
    assert (
        "Ridge scores higher (85) but would make the days either side 8.0 mi and 4.5 mi"
        in (choice["reason"])
    )


def test_climb_is_balanced_too():
    """All the climb is in the first 10 km. Stopping at 8 km instead of 10 km splits it
    more evenly, and that outweighs the distance."""
    distances = [i * 100.0 for i in range(201)]
    smoothed = [100.0 + min(d, 10 * KM) * 0.1 for d in distances]
    climb = Climb.from_profile(distances, smoothed)
    options = [option("flat-split", 10), option("climb-split", 8)]
    assert ids(solve(20 * KM, options, 1, SETTINGS, climb)) == ["climb-split"]
    assert ids(solve(20 * KM, options, 1, SETTINGS)) == ["flat-split"]


def test_an_unscored_stop_counts_as_the_configured_neutral_score():
    options = [option("scored", 10, score=40), option("pending", 10.0, score=None)]
    solved = solve(20 * KM, options, 1, SETTINGS)
    assert ids(solved) == ["pending"]
    assert solved["choices"][0]["reason"].startswith("No score yet: ")


def test_other_sites_in_the_window_are_named_as_not_considered():
    options = [option("a", 10), option("b", 10.2, permitted=False), option("c", 9.9, False)]
    (choice,) = solve(20 * KM, options, 1, SETTINGS)["choices"]
    assert choice["other_options"] == 2
    assert choice["reason"].endswith(
        "2 other sites there are not confirmed legal, so they were not considered."
    )


def test_the_same_input_gives_the_same_plan():
    rng = random.Random(169)
    options = [
        option(
            f"s{i}", rng.uniform(1, 59), permitted=rng.random() < 0.7, score=rng.choice([70, 80])
        )
        for i in range(80)
    ]
    first = solve(60 * KM, options, 4, SETTINGS)
    shuffled = options[:]
    rng.shuffle(shuffled)
    assert solve(60 * KM, shuffled, 4, SETTINGS) == first
    assert solve(60 * KM, options, 4, SETTINGS) == first


def test_exact_ties_break_by_position_then_id():
    options = [option("b", 10), option("a", 10)]
    assert ids(solve(20 * KM, options, 1, SETTINGS)) == ["a"]


@pytest.mark.parametrize(
    "length_km, target_km, days",
    [(30, 10, 3), (32, 10, 3), (35, 10, 4), (25, 10, 3), (24, 10, 3), (22, 10, 2), (8, 10, 1)],
)
def test_a_daily_target_picks_the_number_of_days_closest_to_it(length_km, target_km, days):
    """24 km at 10 km a day is 12 or 8 km days: equally far from 10, so the shorter days."""
    assert days_for_target(length_km * KM, target_km * KM) == days


def test_resolve_nights_from_a_target_distance():
    assert resolve_nights(30 * KM, "T", None, 10 * KM, SETTINGS) == 2


@pytest.mark.parametrize(
    "length_km, nights, target_km, message",
    [
        (8, 3, None, "T is 5.0 mi: 3 nights would make days of 1.2 mi, under the 1.9 mi minimum."),
        (8, None, 10, "T is 5.0 mi, about one day at 6.2 mi a day, so it needs no overnight stop."),
        (30, None, 1, "Choose a daily target of at least 1.9 mi."),
        (30, 0, None, "Choose 1 to 30 nights."),
        (30, 2.5, None, "nights must be a whole number."),
        (30, True, None, "nights must be a whole number."),
        (30, None, "far", "daily_target_m must be a number of metres."),
        (30, None, None, "Give either a number of nights or a daily distance target."),
        (30, 2, 10, "Give either a number of nights or a daily distance target."),
        (500, None, 5, "T would take more than 30 nights at 3.1 mi a day."),
    ],
)
def test_requests_the_route_cannot_answer(length_km, nights, target_km, message):
    target = target_km * KM if isinstance(target_km, int | float) else target_km
    with pytest.raises(AutoPlanError) as error:
        resolve_nights(length_km * KM, "T", nights, target, SETTINGS)
    assert str(error.value).startswith(message)


def test_the_config_is_checked():
    raw = {
        "window_fraction": 0.6,
        "min_day_m": 3000,
        "weights": {"distance": 1, "gain": 0.5, "score": 0.3},
        "gain_floor_m": 100,
        "unscored_score": 50,
        "max_sites": 10,
    }
    with pytest.raises(ValueError, match="window_fraction"):
        parse_settings(raw)
    with pytest.raises(ValueError, match="weights"):
        parse_settings({**raw, "window_fraction": 0.3, "weights": {**raw["weights"], "gain": -1}})
    assert parse_settings({**raw, "window_fraction": 0.5}).window_fraction == 0.5


# --- the endpoint ------------------------------------------------------------------------

X0, Y0 = 1_770_000.0, 2_550_000.0
LENGTH = 30_000


@pytest.fixture
def route(monkeypatch):
    # A steady climb, 0.02 m per metre: every day's gain is its share of the route's.
    monkeypatch.setattr(
        elevation,
        "post_samples",
        lambda points: {
            "samples": [
                {"locationId": i, "value": str(300 + 0.02 * i * 25), "resolution": 1}
                for i in range(len(points))
            ]
        },
    )
    line = LineString((X0, Y0), (X0 + LENGTH, Y0), srid=5070)
    return TrailRoute.objects.create(
        source=TrailRoute.Source.OSM,
        source_id="relation/169",
        osm_id=169,
        name="Long Trail",
        geom=MultiLineString(line, srid=5070).transform(4326, clone=True),
        length_m=LENGTH,
        member_way_ids=[10],
    )


@pytest.fixture
def permitted(monkeypatch):
    """The ids whose verdict is Permitted; every other site keeps its real verdict."""
    allowed: set[str] = set()
    real = plans.legality_verdict

    def verdict(site_row, facts, legal_status):
        result = real(site_row, facts, legal_status)
        if site_row.source_id in allowed:
            return {**result, "verdict": "permitted", "label": "Permitted · designated site"}
        return {**result, "verdict": "unknown"} if result["verdict"] == "permitted" else result

    monkeypatch.setattr(plans, "legality_verdict", verdict)
    return allowed


def site(source_id, along, name=None):
    point = Point(X0 + along, Y0 + 20, srid=5070).transform(4326, clone=True)
    return Campsite.objects.create(
        source=Campsite.Source.OSM, source_id=source_id, name=name or source_id, geom=point
    )


@pytest.fixture
def carol():
    return client_for("carol")


def auto(client, **body):
    return client.post("/api/plans/auto/", {"osm_id": 169, **body}, format="json")


@pytest.mark.django_db
@pytest.mark.integration
def test_auto_plan_proposes_legal_stops_and_works_out_the_days(route, permitted, carol):
    site("node/a", 10_000, "Lean-to A")
    site("node/b", 20_000, "Lean-to B")
    site("node/u", 15_000, "Unverified")
    permitted.update({"node/a", "node/b"})

    answer = auto(carol, nights=2).json()
    assert answer["status"] == "ok"
    assert answer["stop_ids"] == ["node/a", "node/b"]
    assert answer["nights_planned"] == 2 and answer["gaps"] == []
    assert answer["considered"]["mapped"] == 3 and answer["considered"]["mapped_permitted"] == 2
    assert answer["considered"]["candidates_searched"] is False
    days = answer["plan"]["days"]
    assert [d["distance_m"] for d in days] == pytest.approx([10_000] * 3, abs=1)
    assert all(d["gain_m"] is not None and d["loss_m"] is not None for d in days)
    assert [c["reason"] for c in answer["choices"]][0].startswith(
        "No score yet: the only legal stop between mi"
    )
    assert "_line_m" not in answer["plan"]


@pytest.mark.django_db
@pytest.mark.integration
def test_a_day_with_no_legal_stop_is_reported_not_filled(route, permitted, carol):
    site("node/a", 10_000)
    site("node/u", 20_000)  # not permitted
    permitted.add("node/a")

    answer = auto(carol, nights=2).json()
    assert answer["status"] == "partial"
    assert answer["stop_ids"] == ["node/a"]
    assert answer["plan"]["nights"] == 1
    (gap,) = answer["gaps"]
    assert gap["message"].startswith("No legal stop between mi 10.6 and mi 14.3 for night 2")


@pytest.mark.django_db
@pytest.mark.integration
def test_no_legal_stop_at_all_returns_no_plan(route, permitted, carol):
    site("node/u", 15_000)
    answer = auto(carol, nights=1).json()
    assert answer["status"] == "none" and answer["plan"] is None and answer["stop_ids"] == []


@pytest.mark.django_db
@pytest.mark.integration
def test_a_daily_target_sets_the_nights(route, permitted, carol):
    for along in (10_000, 15_000, 20_000):
        site(f"node/{along}", along)
        permitted.add(f"node/{along}")
    answer = auto(carol, daily_target_m=15_000).json()
    assert answer["mode"] == "daily_target" and answer["nights_requested"] == 1
    assert answer["stop_ids"] == ["node/15000"]


@pytest.mark.django_db
@pytest.mark.integration
def test_the_same_request_gives_the_same_plan(route, permitted, carol):
    for along in (9_000, 10_000, 11_000, 19_500, 20_500):
        site(f"node/{along}", along)
        permitted.add(f"node/{along}")
    first = auto(carol, nights=2).json()
    assert auto(carol, nights=2).json() == first


@pytest.mark.django_db
@pytest.mark.integration
def test_the_proposal_saves_and_exports_as_a_normal_plan(route, permitted, carol):
    site("node/a", 15_000, "Lean-to A")
    permitted.add("node/a")
    answer = auto(carol, nights=1).json()
    saved = carol.post(
        "/api/plans/", {"osm_id": 169, "stop_ids": answer["stop_ids"]}, format="json"
    )
    assert saved.status_code == 201
    assert saved.json()["days"] == answer["plan"]["days"]
    gpx = carol.get(f"/api/plans/{saved.json()['id']}/gpx/")
    assert gpx.status_code == 200 and b"Night 1: Lean-to A" in gpx.content


@pytest.mark.django_db
@pytest.mark.integration
@pytest.mark.parametrize(
    "body, message",
    [
        ({"nights": 20}, "Long Trail is 18.6 mi: 20 nights would make days of 0.9 mi"),
        ({"nights": 1, "daily_target_m": 9000}, "Give either a number of nights"),
        ({"nights": "two"}, "nights must be a whole number."),
        ({"nights": 1, "campsites_within_m": 0}, "campsites_within_m must be a whole number"),
        ({"nights": 1, "osm_id": None}, "Say which trail"),
    ],
)
def test_bad_auto_plan_requests_are_400(route, carol, body, message):
    response = auto(carol, **body)
    assert response.status_code == 400
    assert response.json()["error"].startswith(message)


@pytest.mark.django_db
def test_auto_plan_needs_a_sign_in(route):
    from rest_framework.test import APIClient

    assert APIClient().post("/api/plans/auto/", {"osm_id": 169, "nights": 1}).status_code == 401
