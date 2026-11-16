"""
Natural-language trip finder (TM05-170), with the model mocked: valid output, invalid and
out-of-schema output rejected, a timeout, the no-key fallback, the unsupported list,
caching and throttling, the key never in a response, and the keyword parser on example
phrases. No test calls the Anthropic API.
"""

import copy
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from discover import interpret as interpret_module
from discover import schema
from discover.keywords import parse
from django.conf import settings
from rest_framework.test import APIClient

URL = "/api/discover/interpret/"
FAKE_KEY = "sk-ant-test-not-a-real-key-0000"


def reading(**changes):
    """A valid model reply, as a dict, with `changes` applied."""
    base = schema.empty()
    base.update(
        {
            "difficulty": ["moderate"],
            "nights": 2,
            "has_campsites": True,
            "water_view": True,
            "unsupported": [],
        }
    )
    base.update(changes)
    return base


class FakeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        body, stop = self.outcome
        text = body if isinstance(body, str) else json.dumps(body)
        return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def model(monkeypatch, settings):
    """Set a (fake) key and replace the client. `model.reply(body, stop)` or
    `model.fail(exc)` sets what the next call does; `model.messages.calls` records them."""
    settings.ANTHROPIC_API_KEY = FAKE_KEY
    state = SimpleNamespace(messages=FakeMessages((reading(), "end_turn")))
    monkeypatch.setattr(
        interpret_module, "_client", lambda: SimpleNamespace(messages=state.messages)
    )

    def reply(body, stop="end_turn"):
        state.messages.outcome = (body, stop)

    def fail(error):
        state.messages.outcome = error

    state.reply, state.fail = reply, fail
    return state


def ask(text, client=None):
    return (client or APIClient()).post(URL, {"text": text}, format="json")


# --- the model's answer --------------------------------------------------------------------


@pytest.mark.django_db
def test_valid_model_output_becomes_search_filters(model):
    response = ask("two nights, lakeside, moderate climb")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "llm" and body["fallback_reason"] is None
    assert body["model"] == settings.DISCOVER_LLM_MODEL == "claude-haiku-5-5"
    assert body["interpretation"]["difficulty"] == ["moderate"]
    assert body["search"] == {"difficulty": "moderate", "campsites_within_m": "500"}
    assert body["not_filtered"] == ["nights", "water_view"]


@pytest.mark.django_db
def test_the_request_is_capped_short_and_asks_for_json_in_the_schema(model):
    ask("two nights, lakeside, moderate climb")
    (call,) = model.messages.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == settings.DISCOVER_LLM_MAX_TOKENS <= 1000
    assert call["output_config"]["format"] == {
        "type": "json_schema",
        "schema": schema.json_schema(),
    }
    assert call["messages"] == [
        {"role": "user", "content": "<request>two nights, lakeside, moderate climb</request>"}
    ]
    assert "ONLY a JSON object" in call["system"]


def test_the_client_has_a_short_timeout_and_no_retries(settings):
    settings.ANTHROPIC_API_KEY = FAKE_KEY
    client = interpret_module._client()
    assert client.timeout == settings.DISCOVER_LLM_TIMEOUT_S <= 15
    assert client.max_retries == 0


@pytest.mark.django_db
def test_lengths_and_gains_are_sent_to_the_search_in_metres(model):
    model.reply(
        reading(
            min_length_mi=5,
            max_length_mi=10,
            max_gain_ft=2000,
            route_type=["loop"],
            region="adirondacks",
            nights=None,
            has_campsites=None,
        )
    )
    search = ask("a 5 to 10 mile loop in the Adirondacks under 2000 ft").json()["search"]
    assert search == {
        "min_length_m": "8047",
        "max_length_m": "16093",
        "max_gain_m": "610",
        "difficulty": "moderate",
        "route_type": "loop",
        "region": "adirondacks",
    }


@pytest.mark.django_db
def test_unsupported_asks_are_named_back(model):
    model.reply(reading(unsupported=["crowding", "dog rules"]))
    body = ask("two quiet nights by a lake, dog friendly").json()
    assert body["interpretation"]["unsupported"] == ["crowding", "dog rules"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body, why",
    [
        ("not json at all", "Expecting value"),
        ('{"nights": 2}', "missing keys"),
        (reading(results=["Mount Marcy"]), "unknown keys: results"),
        (reading(min_length_mi=1000), "min_length_mi must be between 0 and 300"),
        (reading(max_gain_ft=-5), "max_gain_ft must be between 0 and 30000"),
        (reading(min_length_mi=10, max_length_mi=5), "min_length_mi is above max_length_mi"),
        (reading(nights=2.5), "nights must be a whole number"),
        (reading(nights=True), "nights must be a whole number"),
        (reading(difficulty=["extreme"]), "difficulty has unknown values: extreme"),
        (reading(difficulty="moderate"), "difficulty must be a list"),
        (reading(region="colorado"), "region must be one of"),
        (reading(water_view="yes"), "water_view must be true, false or null"),
        (reading(weights={"water": 0.5}), "weights must be null or an object with exactly"),
        (
            reading(weights={**dict.fromkeys(schema.factors()), "water": 2}),
            "weights.water must be between 0 and 1",
        ),
        (reading(unsupported=["a", "b", "c", "d", "e", "f"]), "more than 5 items"),
        (reading(unsupported=["x" * 61]), "1-60 characters"),
        (reading(unsupported=["<script>"]), "plain text"),
    ],
)
def test_invalid_or_out_of_schema_output_is_rejected_and_the_keywords_take_over(
    model, body, why, caplog
):
    model.reply(body)
    answer = ask("two nights, lakeside, moderate climb").json()
    assert answer["source"] == "keywords"
    assert answer["fallback_reason"] == "invalid_output"
    assert why in caplog.text
    # The keyword parser's reading, not anything from the rejected reply.
    assert answer["interpretation"] == parse("two nights, lakeside, moderate climb")


@pytest.mark.django_db
@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_a_truncated_or_refused_reply_falls_back(model, stop):
    model.reply(reading(), stop)
    answer = ask("two nights, lakeside").json()
    assert (answer["source"], answer["fallback_reason"]) == ("keywords", "invalid_output")


@pytest.mark.django_db
def test_a_timeout_falls_back_to_the_keyword_parser(model):
    model.fail(anthropic.APITimeoutError(request=httpx2.Request("POST", "https://example.test")))
    answer = ask("an easy 5 mile loop near a lake").json()
    assert (answer["source"], answer["fallback_reason"]) == ("keywords", "timeout")
    assert answer["interpretation"]["route_type"] == ["loop"]


@pytest.mark.django_db
def test_an_api_error_falls_back_too(model):
    request = httpx2.Request("POST", "https://example.test")
    error = anthropic.InternalServerError(
        "overloaded", response=httpx2.Response(529, request=request), body=None
    )
    model.fail(error)
    answer = ask("an easy loop").json()
    assert (answer["source"], answer["fallback_reason"]) == ("keywords", "api_error")


@pytest.mark.django_db
def test_without_a_key_the_model_is_never_called(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = ""

    def no_client():
        raise AssertionError("the model must not be called without a key")

    monkeypatch.setattr(interpret_module, "_client", no_client)
    answer = ask("two nights, lakeside, moderate climb").json()
    assert (answer["source"], answer["fallback_reason"], answer["model"]) == (
        "keywords",
        "no_key",
        None,
    )
    assert answer["search"] == {"difficulty": "moderate", "campsites_within_m": "500"}


@pytest.mark.django_db
def test_the_key_never_reaches_the_browser(model):
    model.reply("not json")
    for text in ("two nights, lakeside", "an easy loop"):
        assert FAKE_KEY not in ask(text).content.decode()


# --- caching and throttling ----------------------------------------------------------------


@pytest.mark.django_db
def test_identical_requests_are_cached_briefly(model):
    first = ask("Two nights,  lakeside").json()
    second = ask("two nights, LAKESIDE").json()
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["interpretation"] == first["interpretation"]
    assert len(model.messages.calls) == 1


@pytest.mark.django_db
def test_a_transient_failure_is_not_cached(model):
    model.fail(anthropic.APITimeoutError(request=httpx2.Request("POST", "https://example.test")))
    assert ask("two nights").json()["fallback_reason"] == "timeout"
    model.reply(reading())
    again = ask("two nights").json()
    assert (again["source"], again["cached"]) == ("llm", False)


@pytest.mark.django_db
def test_the_endpoint_is_throttled_per_client(model, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(
        ScopedRateThrottle,
        "THROTTLE_RATES",
        {**ScopedRateThrottle.THROTTLE_RATES, "discover-interpret": "3/min"},
    )
    client = APIClient(REMOTE_ADDR="203.0.113.9")
    codes = [ask(f"loop number {i}", client).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]
    body = ask("one more", client).json()
    assert body["error"].startswith("Too many trip descriptions from this address.")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body, message",
    [
        ({}, "Describe the trip you want"),
        ({"text": "   "}, "Describe the trip you want"),
        ({"text": 7}, "Describe the trip you want"),
        ({"text": "x" * 301}, "Keep it under 300 characters."),
    ],
)
def test_bad_requests_are_400(body, message):
    response = APIClient().post(URL, body, format="json")
    assert response.status_code == 400
    assert response.json()["error"].startswith(message)


# --- the schema --------------------------------------------------------------------------


def test_the_json_schema_is_closed_and_lists_every_field():
    shape = schema.json_schema()
    assert shape["additionalProperties"] is False
    assert shape["required"] == list(schema.fields()) == list(shape["properties"])
    weights = shape["properties"]["weights"]["anyOf"][0]
    assert weights["additionalProperties"] is False and weights["required"] == list(
        schema.factors()
    )


def test_validate_normalises_order_and_repeats():
    out = schema.validate(
        reading(difficulty=["hard", "easy"], unsupported=["Crowding", "crowding", "  dog  rules "])
    )
    assert out["difficulty"] == ["easy", "hard"]
    assert out["unsupported"] == ["Crowding", "dog rules"]


def test_all_null_weights_mean_no_weights():
    out = schema.validate(reading(weights=dict.fromkeys(schema.factors())))
    assert out["weights"] is None


# --- the keyword parser: ten example phrases ---------------------------------------------


def expect(**fields):
    out = schema.empty()
    out.update(fields)
    return out


PHRASES = [
    (
        "two nights, lakeside, moderate climb",
        expect(difficulty=["moderate"], nights=2, water_view=True),
    ),
    (
        "an easy 5 mile loop near a lake",
        expect(
            min_length_mi=4.0,
            max_length_mi=6.0,
            difficulty=["easy"],
            route_type=["loop"],
            water_view=True,
        ),
    ),
    (
        "under 10 miles with less than 2,000 ft of climbing",
        expect(max_length_mi=10.0, max_gain_ft=2000.0),
    ),
    (
        "quiet overnight in the High Peaks, dog friendly",
        expect(nights=1, region="adirondacks", unsupported=["crowding", "dog rules"]),
    ),
    (
        "a weekend point-to-point in Vermont",
        expect(route_type=["point_to_point"], nights=2, region="green-mountains-vt"),
    ),
    (
        "flat day hike, out and back, close to the road",
        expect(
            max_gain_ft=500.0,
            route_type=["out_and_back"],
            nights=0,
            unsupported=["easy access from the road"],
        ),
    ),
    (
        "strenuous 3 day backpacking trip in the White Mountains with at least 3000 ft of gain",
        expect(
            min_gain_ft=3000.0,
            difficulty=["hard"],
            nights=2,
            has_campsites=True,
            region="white-mountains-nh",
        ),
    ),
    (
        "8-12 mi loop with a lean-to, sheltered from the wind",
        expect(
            min_length_mi=8.0,
            max_length_mi=12.0,
            route_type=["loop"],
            has_campsites=True,
            sheltered=True,
        ),
    ),
    (
        "sheltered campsite by a river, good fishing, no bugs please",
        expect(
            has_campsites=True,
            water_view=True,
            sheltered=True,
            unsupported=["fishing", "bugs"],
        ),
    ),
    ("somewhere nice", expect()),
]


@pytest.mark.parametrize("text, expected", PHRASES, ids=[p[0][:40] for p in PHRASES])
def test_the_keyword_parser_reads_example_phrases(text, expected):
    assert parse(text) == schema.validate(copy.deepcopy(expected))


def test_the_keyword_parser_never_guesses_a_region_from_two():
    assert parse("Adirondacks or Vermont, a loop")["region"] is None
