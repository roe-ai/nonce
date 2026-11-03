import pytest

from privato import broker, db
from privato.errors import AccessError

from conftest import TEST_USER


async def grant(agent, **kw):
    args = dict(
        user_request="When does my flight to Tokyo leave?",
        justification="Need the airline confirmation",
        query="from:united.com Tokyo OR NRT",
        scopes=["gmail.metadata", "gmail.body"],
    )
    return await broker.request_access(agent, **{**args, **kw})


async def test_legit_request_is_scoped_and_readable(agent, detector):
    g = await grant(agent)
    assert g["status"] == "active"
    res = await broker.gmail_search(agent, g["grant_token"], "")
    assert [m["id"] for m in res["messages"]] == ["m01"]
    assert "body" not in res["messages"][0]
    read = await broker.gmail_read(agent, g["grant_token"], "m01")
    assert "UA837" in read["message"]["body"]


async def test_search_cannot_escape_the_grant_filter(agent, detector):
    g = await grant(agent)
    res = await broker.gmail_search(agent, g["grant_token"], "statement")
    assert res["messages"] == []


async def test_metadata_scope_hides_bodies(agent, detector):
    g = await grant(agent, scopes=["gmail.metadata"])
    await broker.gmail_search(agent, g["grant_token"], "")
    read = await broker.gmail_read(agent, g["grant_token"], "m01")
    assert "body" not in read["message"] and "snippet" not in read["message"]


async def test_bulk_request_is_denied(agent, detector):
    detector.access_signals["crawl"] = 2.9
    g = await grant(agent, query="in:anywhere")
    assert g["status"] == "denied"
    with pytest.raises(AccessError) as e:
        await broker.gmail_search(agent, g["grant_token"], "")
    assert e.value.code == "grant_denied"


async def test_agent_initiated_long_request_waits_for_user(agent, detector):
    detector.access_signals["user_initiated"] = 0.05
    g = await grant(agent, duration_minutes=720)
    assert g["status"] == "pending"
    alert = await db.one("SELECT * FROM alerts WHERE grant_id = ?", g["grant_id"])
    assert alert["needs_approval"] == 1
    await broker.approve(g["grant_id"])
    assert (await broker.check_access(agent, g["grant_token"]))["status"] == "active"


async def test_no_signals_sends_request_to_user(agent, detector):
    detector.access_signals = {}
    g = await grant(agent)
    assert g["status"] == "pending"


async def test_drifting_search_revokes(agent, detector):
    g = await grant(agent)
    detector.search_signals = {"serves": 0.04, "crawl": 0.5, "category": "finance"}
    with pytest.raises(AccessError) as e:
        await broker.gmail_search(agent, g["grant_token"], "bank statement")
    assert e.value.code == "grant_revoked"
    assert (await broker.check_access(agent, g["grant_token"]))["status"] == "revoked"


async def test_other_agents_token_is_refused_and_revoked(agent, detector):
    g = await grant(agent)
    thief, _ = await broker.create_agent(TEST_USER, "thief")
    with pytest.raises(AccessError) as e:
        await broker.gmail_search(thief, g["grant_token"], "")
    assert e.value.code == "token_mismatch"
    assert (await broker.check_access(agent, g["grant_token"]))["status"] == "revoked"


async def test_reading_unreturned_message_revokes(agent, detector):
    g = await grant(agent)
    with pytest.raises(AccessError) as e:
        await broker.gmail_read(agent, g["grant_token"], "m03")
    assert e.value.code == "grant_revoked"


async def test_injection_body_is_withheld_and_grant_tightened(agent, detector):
    g = await grant(agent, query="from:united")
    await broker.gmail_search(agent, g["grant_token"], "")
    detector.content_signals = {"injection": 0.97}
    read = await broker.gmail_read(agent, g["grant_token"], "m08")
    assert read["message"]["body"].startswith("[Withheld")
    # After an injection, a weak-match search (0.4) that would normally only warn now revokes.
    detector.search_signals = {"serves": 0.4, "crawl": 0.3, "category": "travel"}
    with pytest.raises(AccessError):
        await broker.gmail_search(agent, g["grant_token"], "codes")


async def test_rapid_searches_revoke_as_crawling(agent, detector):
    g = await grant(agent)
    with pytest.raises(AccessError) as e:
        for _ in range(20):
            await broker.gmail_search(agent, g["grant_token"], "flight")
    assert e.value.code == "grant_revoked"


async def test_expired_grant_is_refused(agent, detector):
    g = await grant(agent)
    await db.update("grants", g["grant_id"], expires_at=db.now() - 1)
    with pytest.raises(AccessError) as e:
        await broker.gmail_search(agent, g["grant_token"], "")
    assert e.value.code == "grant_expired"
