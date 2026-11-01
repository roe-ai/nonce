from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from nonce import broker, db, recall, sms
from nonce.main import app
from nonce.policy import MODES, AccessContext, decide_access, is_offline
from nonce.sources import SOURCES

ADMIN = {"Authorization": "Bearer test-admin"}
GMAIL = SOURCES["gmail"]
CALM = AccessContext(requests_last_hour=0, known_categories={"travel"}, offline=False, history_size=10)
CLEAR = {"user_initiated": 0.95, "consistent": 0.9, "scope_fits": 0.9, "crawl": 0.2, "category": "travel", "familiar": 0.9}


def decide(mode: str, *, scopes=("gmail.metadata",), ttl_s=600, ctx=CALM, **signals):
    return decide_access(
        src=GMAIL, mode=MODES[mode], scopes=list(scopes), constraint="from:united.com", ttl_s=ttl_s, signals={**CLEAR, **signals}, ctx=ctx
    )


# --- Rules -----------------------------------------------------------------------


def test_hard_limits_hold_in_every_mode():
    for name in MODES:
        assert decide(name, crawl=2.9).outcome == "deny"
        assert decide(name, ttl_s=3 * 86400).outcome == "deny"


def test_relaxed_lets_clearly_asked_money_questions_through_but_never_login_codes():
    assert decide("relaxed", category="finance").outcome == "allow"
    assert decide("standard", category="finance").outcome == "ask"
    assert decide("relaxed", category="finance", user_initiated=0.6).outcome == "ask"
    assert decide("relaxed", category="security").outcome == "ask"


def test_relaxed_allows_longer_access_and_cautious_less():
    assert decide("relaxed", ttl_s=2 * 3600).outcome == "allow"
    assert decide("standard", ttl_s=2 * 3600).outcome == "ask"
    assert decide("cautious", ttl_s=20 * 60).outcome == "ask"


def test_cautious_asks_before_full_text_and_about_unfamiliar_questions():
    assert decide("cautious").outcome == "allow"
    assert "read whole emails" in decide("cautious", scopes=("gmail.metadata", "gmail.body")).reason
    assert "haven't asked anything like this" in decide("cautious", familiar=0.1).reason
    first = AccessContext(requests_last_hour=0, known_categories={"travel"}, offline=False, history_size=0)
    assert "first thing" in decide("cautious", ctx=first).reason
    assert "never asked for shopping" in decide("cautious", category="shopping").reason
    assert decide("standard", familiar=0.1).outcome == "allow"


def test_offline_hours_wrap_past_midnight():
    assert is_offline(23, 22, 7) and is_offline(3, 22, 7) and not is_offline(12, 22, 7)
    assert is_offline(2, 1, 6) and not is_offline(6, 1, 6)
    assert not is_offline(3, 0, 0)


# --- Through the broker ------------------------------------------------------------


@pytest.fixture
async def fresh():
    """A new user with Gmail connected and one app, so history starts empty."""
    uid = f"user-{db.new_id()[:6]}"
    await db.insert("users", {"id": uid, "google_sub": uid, "email": f"{uid}@example.com", "created_at": db.now()})
    await db.insert("connections", {"user_id": uid, "provider": "gmail", "mode": "google", "account": "x", "status": "active", "created_at": db.now()})
    app_row, _ = await broker.create_agent(uid, "Claude", "claude")
    return uid, app_row


async def ask(agent, question, query="from:united.com"):
    return await broker.request_access(agent, user_request=question, justification="Answer the question", query=query)


async def test_cautious_compares_new_questions_with_what_recall_found(fresh, detector, monkeypatch):
    uid, agent = fresh
    await db.update("agents", agent["id"], mode="cautious")
    agent = {**agent, "mode": "cautious"}

    first = await ask(agent, "When does my flight to Tokyo leave?")
    assert first["status"] == "pending" and "first thing" in first["reason"]
    await broker.approve(first["grant_id"])

    async def fake_recall(question, source_label, history):
        assert "When does my flight to Tokyo leave?" in [h["question"] for h in history]
        tokyo = "When does my flight to Tokyo leave?"
        return recall.Recall(compare=[tokyo], closest=(tokyo, 0.0), queries=["flight", "boarding"], by="luna")

    monkeypatch.setattr(recall, "recall", fake_recall)
    detector.access_signals["familiar"] = 0.92
    g = await ask(agent, "What time do I board my plane to Japan?")
    assert g["status"] == "active"
    assert detector.last_access_state["previous_requests"] == ["When does my flight to Tokyo leave?"]
    stored = await db.one("SELECT signals FROM grants WHERE id = ?", g["grant_id"])
    assert stored["signals"]["recall_queries"] == ["flight", "boarding"] and stored["signals"]["closest"].startswith("When does")

    detector.access_signals["familiar"] = 0.08
    g = await ask(agent, "Which newsletters did I get this week?", query="category:promotions newer_than:7d")
    assert g["status"] == "pending" and "haven't asked anything like this" in g["reason"]


async def test_recall_without_luna_falls_back_to_matching_words():
    history = [
        {"id": "a", "question": "When does my flight to Tokyo leave?", "source": "Gmail", "date": "2026-10-28"},
        {"id": "b", "question": "Show my bank statement", "source": "Gmail", "date": "2026-10-27"},
    ]
    found = await recall.recall("Tokyo flight seat number", "Gmail", history)
    assert found.by == "words" and found.closest[0] == "When does my flight to Tokyo leave?"


async def test_requests_in_offline_hours_wait_quietly(fresh, detector, monkeypatch):
    uid, agent = fresh
    hour = datetime.now(ZoneInfo("America/Los_Angeles")).hour
    await db.update("users", uid, offline_start=hour, offline_end=(hour + 1) % 24, timezone="America/Los_Angeles",
                    phone="+14155550100", phone_verified_at=db.now())  # fmt: skip
    sent = []

    async def fake_send(phone, body):
        sent.append(body)
        return True

    monkeypatch.setattr(sms, "send_text", fake_send)
    g = await ask(agent, "When does my flight to Tokyo leave?")
    assert g["status"] == "pending" and "offline hours" in g["reason"]
    assert sent == [], "no texts while you're offline"


async def test_dashboard_sets_mode_offline_hours_and_previews_modes(fresh, detector):
    uid, agent = fresh
    await ask(agent, "When does my flight to Tokyo leave?")
    detector.access_signals["category"] = "finance"
    await ask(agent, "What was my card bill last month?", query="from:chase.com statement")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={**ADMIN, "X-Nonce-User": uid}) as c:
        assert (await c.patch(f"/admin/agents/{agent['id']}", json={"mode": "loose"})).status_code == 422
        assert (await c.patch(f"/admin/agents/{agent['id']}", json={"mode": "relaxed"})).json()["mode"] == "relaxed"
        assert [a["mode"] for a in (await c.get("/admin/agents")).json()] == ["relaxed"]

        preview = (await c.get(f"/admin/agents/{agent['id']}/modes")).json()
        assert preview["requests"] == 2
        assert preview["modes"]["relaxed"]["ask"] < preview["modes"]["standard"]["ask"] <= preview["modes"]["cautious"]["ask"]

        assert (await c.put("/admin/me/offline", json={"start": 22, "end": 7, "timezone": "Mars/Base"})).status_code == 400
        me = (await c.put("/admin/me/offline", json={"start": 22, "end": 7, "timezone": "Europe/London"})).json()
        assert (me["offline_start"], me["offline_end"], me["timezone"]) == (22, 7, "Europe/London")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={**ADMIN, "X-Nonce-User": "user-test"}) as c:
        assert (await c.patch(f"/admin/agents/{agent['id']}", json={"mode": "relaxed"})).status_code == 404
