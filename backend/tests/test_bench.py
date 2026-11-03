from bench.run import load_cases, misses, run, score
from privato.signals import NoSignals
from privato.sources import SOURCES

from conftest import SAFE_ACCESS, SAFE_SEARCH

GRANTS, CASES = load_cases()


class Oracle:
    """Knows every label, so it shows each one is reachable through policy."""

    def __init__(self) -> None:
        self.expect = {self._key(c): c["expect"] for c in CASES}

    @staticmethod
    def _key(c: dict) -> str:
        return c.get("search_query") or c.get("text") or f"{c['user_request']}|{c['filter']}"

    async def access(self, state):
        if self.expect[f"{state['user_request']}|{state['filter']}"] == "allow":
            return dict(SAFE_ACCESS)
        return {**SAFE_ACCESS, "user_initiated": 0.1, "crawl": 2.9}

    async def search(self, state):
        if self.expect[state["search_query"]] == "allow":
            return dict(SAFE_SEARCH)
        return {**SAFE_SEARCH, "serves": 0.05}

    async def content(self, state):
        return {"injection": 0.02 if self.expect[state["text"]] == "allow" else 0.95}


def test_cases_are_well_formed():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert c["kind"] in {"access", "search", "content"} and c["expect"] in {"allow", "stop"}, c["id"]
        src = GRANTS[c["grant"]]["source"] if c["kind"] == "search" else c["source"]
        assert src in SOURCES, c["id"]
        if c["kind"] == "access":
            assert c["filter"].strip() and c["minutes"] <= 60, c["id"]


async def test_every_label_is_reachable():
    results = await run(Oracle(), GRANTS, CASES)
    assert misses(results) == []


async def test_without_a_detector_requests_come_to_you_and_nothing_else_is_caught():
    sc = score(await run(NoSignals(), GRANTS, CASES))
    assert sc["access"]["caught"] == sc["access"]["should_stop"]
    assert sc["access"]["false_alarms"] == sc["access"]["should_allow"]
    assert sc["search"]["caught"] == 0 and sc["content"]["caught"] == 0
