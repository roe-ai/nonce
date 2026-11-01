"""Any detector plugs in: an HTTP service or a Python class. Policy only ever sees the known fields."""

import json

import httpx

from nonce import broker, signals
from nonce.config import settings


class PluggedIn:
    async def access(self, state):
        return {"user_initiated": 0.9, "consistent": 0.9, "scope_fits": 0.9, "crawl": 0.1, "category": "travel", "model": "secret-v3"}

    async def search(self, state):
        raise RuntimeError("down")

    async def content(self, state):
        return {"injection": True}


async def test_an_http_detector_gets_the_kind_and_state_and_only_known_fields_come_back():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"serves": 0.8, "crawl": 1, "category": "made-up", "trace": "x", "model": "m"})

    d = signals.HttpDetector("https://signals.example", "k", 3.0, transport=httpx.MockTransport(handler))
    out = await d.search({"search_query": "flights"})
    assert out == {"serves": 0.8, "crawl": 1.0, "category": "other"}
    assert seen == [("Bearer k", {"kind": "search", "state": {"search_query": "flights"}})]


async def test_a_failing_http_detector_means_no_signals():
    d = signals.HttpDetector("https://signals.example", None, 3.0, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert await d.access({}) is None


async def test_a_python_class_plugs_in_and_its_extras_and_failures_are_contained(monkeypatch):
    monkeypatch.setattr(settings(), "signals_detector", "test_signals:PluggedIn")
    d = signals.load_detector()
    assert "model" not in (await d.access({}))
    assert await d.search({}) is None, "a crash is no signals, so the user decides"
    assert await d.content({}) is None, "booleans aren't scores"


async def test_with_no_detector_requests_wait_for_the_user(agent):
    broker.use_detector(signals.NoSignals())
    g = await broker.request_access(agent, user_request="Flights?", justification="Find", query="from:united.com")
    assert g["status"] == "pending"


class FakeDecisions:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def create(self, **kwargs):
        from types import SimpleNamespace

        self.calls.append(kwargs)
        return SimpleNamespace(answers=self.answers, model="m")


def _answer(**kw):
    from types import SimpleNamespace

    return SimpleNamespace(**kw)


async def test_an_openai_key_is_enough_for_signals_through_the_decisions_api(monkeypatch):
    from types import SimpleNamespace

    decisions = FakeDecisions(
        [
            _answer(type="predicate", probability=0.93),
            _answer(type="predicate", probability=0.88),
            _answer(type="predicate", probability=0.81),
            _answer(type="score", score=0.4),
            _answer(type="choice", choice="travel", confidence=0.97),
            _answer(type="refusal"),
        ]
    )
    d = signals.OpenAIDetector(SimpleNamespace(decisions=decisions), "gpt-6-luna", 3.0)
    out = await d.access({"user_request": "Flights?", "previous_requests": ["When is my flight?"]})
    assert out == {"user_initiated": 0.93, "consistent": 0.88, "scope_fits": 0.81, "crawl": 0.4, "category": "travel", "category_confidence": 0.97}
    call = decisions.calls[0]
    assert call["model"] == "gpt-6-luna"
    assert [q["name"] for q in call["questions"]][-1] == "familiar", "Cautious history adds the familiarity question"
    assert '"Flights?"' in call["input"][1]["content"]

    monkeypatch.setattr(settings(), "openai_api_key", "sk-test")
    assert isinstance(signals.load_detector(), signals.OpenAIDetector)
    monkeypatch.setattr(settings(), "signals_url", "https://signals.example")
    assert isinstance(signals.load_detector(), signals.HttpDetector), "a signals service set explicitly wins"


async def test_a_failing_decisions_call_means_no_signals():
    from types import SimpleNamespace

    class Down:
        async def create(self, **kwargs):
            raise RuntimeError("rate limited")

    d = signals.OpenAIDetector(SimpleNamespace(decisions=Down()), "gpt-6-luna", 3.0)
    assert await d.content({"text": "hi"}) is None
