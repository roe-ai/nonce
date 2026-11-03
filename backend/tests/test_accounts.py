import re

import httpx
import pytest

from privato import broker, db, sms
from privato.main import app
from privato.notify import review_link

from conftest import TEST_USER

ADMIN = {"Authorization": "Bearer test-admin"}


def client(user_id: str | None = TEST_USER) -> httpx.AsyncClient:
    headers = {**ADMIN, **({"X-Privato-User": user_id} if user_id else {})}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers)


async def pending_grant(agent, detector) -> dict:
    detector.access_signals["user_initiated"] = 0.05
    return await broker.request_access(
        agent, user_request="(scheduled task)", justification="Check flights", query="from:united.com", duration_minutes=720
    )


@pytest.fixture
async def other_user():
    uid = f"user-{db.new_id()[:6]}"
    await db.insert("users", {"id": uid, "google_sub": uid, "email": f"{uid}@example.com", "created_at": db.now()})
    return uid


async def test_dashboard_requires_a_user():
    async with client(None) as c:
        assert (await c.get("/admin/agents")).status_code == 401
    async with client("nobody") as c:
        assert (await c.get("/admin/agents")).status_code == 401


async def test_users_only_see_and_act_on_their_own(agent, detector, other_user):
    g = await pending_grant(agent, detector)
    async with client(other_user) as c:
        assert all(x["id"] != agent["id"] for x in (await c.get("/admin/agents")).json())
        assert (await c.get("/admin/grants?status=pending")).json() == []
        assert (await c.get("/admin/events")).json() == []
        assert (await c.post(f"/admin/grants/{g['grant_id']}/approve")).status_code == 404
        assert (await c.post(f"/admin/agents/{agent['id']}/disable")).status_code == 404
    async with client() as c:
        assert g["grant_id"] in [x["id"] for x in (await c.get("/admin/grants?status=pending")).json()]


async def test_phone_is_verified_with_a_code(other_user, caplog):
    async with client(other_user) as c:
        assert (await c.post("/admin/me/phone", json={"phone": "12"})).status_code == 400
        assert (await c.post("/admin/me/phone", json={"phone": "(415) 555-0100"})).json()["phone"] == "+14155550100"
        code = re.search(r"Code for \+14155550100: (\d{6})", caplog.text).group(1)
        assert (await c.post("/admin/me/phone/verify", json={"code": "000000" if code != "000000" else "111111"})).status_code == 400
        me = (await c.post("/admin/me/phone/verify", json={"code": code})).json()
        assert me["phone"] == "+14155550100" and me["phone_verified_at"]


async def test_pending_request_texts_the_user_who_approves_from_the_link(agent, detector, monkeypatch):
    await db.q("UPDATE users SET phone = '+14155550100', phone_verified_at = ? WHERE id = ?", db.now(), TEST_USER)
    sent: list[tuple[str, str]] = []

    async def fake_send(phone, body):
        sent.append((phone, body))
        return True

    monkeypatch.setattr(sms, "send_text", fake_send)
    g = await pending_grant(agent, detector)
    assert sent and sent[0][0] == "+14155550100"
    link = review_link(g["grant_id"])
    assert link in sent[0][1]

    path = link.split("://", 1)[1].split("/", 1)[1]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        page = await c.get(f"/{path}")
        assert "wants to read your email" in page.text and "Emails from united.com" in page.text
        assert (await c.get(f"/approvals/{g['grant_id']}?sig=bad")).status_code == 403
        done = await c.post(f"/{path}", data={"action": "approve"})
        assert "Allowed" in done.text
    assert (await broker.check_access(agent, g["grant_token"]))["status"] == "active"


async def test_texting_off_hides_the_phone_setting_and_sends_nothing(detector, agent, monkeypatch):
    from privato.config import settings

    monkeypatch.setattr(settings(), "sms_enabled", False)
    sent = []

    async def fake_send(phone, body):
        sent.append(body)
        return True

    monkeypatch.setattr(sms, "send_text", fake_send)
    async with client() as c:
        assert (await c.get("/admin/notifications")).json()["sms"] is False
        assert (await c.post("/admin/me/phone", json={"phone": "(415) 555-0100"})).status_code == 404
    await db.q("UPDATE users SET phone = '+14155550100', phone_verified_at = ? WHERE id = ?", db.now(), TEST_USER)
    detector.access_signals = {**detector.access_signals, "category": "finance"}
    await broker.request_access(agent, user_request="My statement?", justification="Find it", query="from:chase.com")
    assert sent == []
