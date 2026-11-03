import json

import httpx
import pytest

from privato import broker, db, webpush
from privato.config import settings
from privato.main import app

from conftest import TEST_USER

ADMIN = {"Authorization": "Bearer test-admin", "X-Privato-User": TEST_USER}
PHONE = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BPk", "auth": "au"}, "device": "iPhone"}


@pytest.fixture
def pushes(monkeypatch):
    public, private = webpush.generate_keys()
    monkeypatch.setattr(settings(), "vapid_public_key", public)
    monkeypatch.setattr(settings(), "vapid_private_key", private)
    sent: list[dict] = []
    status: dict[str, int | None] = {"next": None}

    def fake_deliver(sub, data, urgent):
        sent.append({"endpoint": sub["endpoint"], "urgent": urgent, **json.loads(data)})
        return status["next"]

    monkeypatch.setattr(webpush, "_deliver", fake_deliver)
    return sent, status


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=ADMIN)


async def test_keys_are_a_p256_pair_that_signs():
    from py_vapid import Vapid

    public, private = webpush.generate_keys()
    assert len(public) == 87 and len(private) == 43
    assert Vapid.from_string(private).sign({"sub": "mailto:a@b.c", "aud": "https://web.push.apple.com"})["Authorization"]


async def test_phone_subscribes_and_gets_approval_requests_until_it_goes_away(agent, detector, pushes):
    sent, status = pushes
    async with client() as c:
        assert (await c.get("/admin/notifications")).json()["push_key"] == settings().vapid_public_key
        assert (await c.post("/admin/push", json={**PHONE, "endpoint": "http://insecure"})).status_code == 422
        assert (await c.post("/admin/push", json=PHONE)).json() == {"ok": True}
        assert (await c.post("/admin/push", json=PHONE)).json() == {"ok": True}, "re-subscribing replaces, not duplicates"
        assert (await c.get("/admin/notifications")).json()["push_devices"] == 1
        assert (await c.post("/admin/push/test")).json() == {"sent": 1}

    detector.access_signals["user_initiated"] = 0.05
    g = await broker.request_access(agent, user_request="(scheduled)", justification="Check", query="from:united.com")
    assert g["status"] == "pending"
    alert = sent[-1]
    assert alert["title"].endswith("wants to read your email") and alert["urgent"] and alert["url"] == "/"

    status["next"] = 410
    await broker.request_access(agent, user_request="Summarize my newsletters", justification="Check", query="category:promotions")
    assert await db.q("SELECT 1 FROM push_subscriptions WHERE endpoint = ?", PHONE["endpoint"]) == [], "gone phones are dropped"


async def test_offline_hours_keep_the_phone_quiet(agent, detector, pushes, monkeypatch):
    sent, _ = pushes
    async with client() as c:
        await c.post("/admin/push", json={**PHONE, "endpoint": "https://fcm.googleapis.com/x"})
    monkeypatch.setattr(broker, "is_offline", lambda *a: True)
    detector.access_signals["user_initiated"] = 0.05
    before = len(sent)
    g = await broker.request_access(agent, user_request="(night)", justification="Check", query="from:united.com")
    assert g["status"] == "pending" and len(sent) == before
    async with client() as c:
        await c.post("/admin/push/remove", json={"endpoint": "https://fcm.googleapis.com/x"})
        assert (await c.get("/admin/notifications")).json()["push_devices"] == 0
