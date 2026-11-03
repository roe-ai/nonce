from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from privato import accounts, broker, db, google_oauth
from privato.errors import AccessError
from privato.main import app

from fake_gmail import FakeGmail

USER = "user-two-inboxes"
ADMIN = {"Authorization": "Bearer test-admin", "X-Privato-User": USER}
HOME, WORK = "me@home.example", "me@work.example"


def _flight(id_: str, to: str) -> dict:
    return {
        "id": id_,
        "thread_id": id_,
        "sender": "United <receipts@united.com>",
        "to": to,
        "subject": f"Flight confirmation for {to}",
        "date": "2026-10-20T09:12:00",
        "snippet": "Confirmation",
        "body": "Your flight",
    }


@pytest.fixture(scope="module", autouse=True)
async def two_inboxes():
    await db.insert("users", {"id": USER, "google_sub": "two-inboxes", "email": HOME, "created_at": db.now()})
    await accounts.save(USER, "gmail", "google", HOME, "x")
    await accounts.save(USER, "gmail", "google", WORK, "x")
    broker.use_provider(FakeGmail([_flight("same-id", HOME)]), "gmail", HOME)
    broker.use_provider(FakeGmail([_flight("same-id", WORK)]), "gmail", WORK)
    yield
    broker.use_provider(None, "gmail", HOME)
    broker.use_provider(None, "gmail", WORK)


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=ADMIN)


async def _ids() -> dict[str, str]:
    return {r["account"]: r["id"] for r in await accounts.of(USER, "gmail")}


async def test_apps_read_every_account_unless_they_name_some(detector):
    agent, _ = await broker.create_agent(USER, "Claude")
    gmail = next(s for s in (await broker.list_sources(agent))["sources"] if s["source"] == "gmail")
    assert gmail["accounts"] == [HOME, WORK]

    g = await broker.request_access(agent, user_request="Any flight emails?", justification="Find flights", query="from:united.com")
    assert g["account"] == f"{HOME}, {WORK}"
    found = (await broker.gmail_search(agent, g["grant_token"]))["messages"]
    assert sorted(m["account"] for m in found) == [HOME, WORK]
    assert len({m["id"] for m in found}) == 2, "the same message id in two inboxes stays two items"
    work_item = next(m for m in found if m["account"] == WORK)
    opened = (await broker.gmail_read(agent, g["grant_token"], work_item["id"]))["message"]
    assert opened["to"] == WORK and opened["account"] == WORK

    one = await broker.request_access(agent, user_request="Work flights?", justification="Find", query="from:united.com", account="ME@work.example")
    assert one["account"] == WORK
    found = (await broker.gmail_search(agent, one["grant_token"]))["messages"]
    assert [m["to"] for m in found] == [WORK] and "account" not in found[0]

    with pytest.raises(AccessError) as e:
        await broker.request_access(agent, user_request="x", justification="y", query="from:a.com", account="other@example.com")
    assert e.value.code == "unknown_account" and WORK in e.value.message


async def test_you_change_the_accounts_of_a_waiting_request(detector):
    agent, _ = await broker.create_agent(USER, "ChatGPT")
    detector.access_signals = {**detector.access_signals, "category": "finance"}
    g = await broker.request_access(agent, user_request="My card statement?", justification="Find it", query="from:chase.com", account=[HOME, WORK])
    assert g["status"] == "pending"
    ids = await _ids()
    async with client() as c:
        assert (await c.put(f"/admin/grants/{g['grant_id']}/accounts", json={"connection_ids": []})).status_code == 400
        assert (await c.put(f"/admin/grants/{g['grant_id']}/accounts", json={"connection_ids": [ids[WORK]]})).status_code == 200
        row = await db.one("SELECT account, account_ids FROM grants WHERE id = ?", g["grant_id"])
        assert row["account"] == WORK and row["account_ids"] == [ids[WORK]]
        await c.post(f"/admin/grants/{g['grant_id']}/approve")
        assert (await c.put(f"/admin/grants/{g['grant_id']}/accounts", json={"connection_ids": [ids[HOME]]})).status_code == 409


async def test_pausing_an_account_cuts_it_off_and_ends_access_left_with_none(detector):
    agent, _ = await broker.create_agent(USER, "Cursor")
    every = await broker.request_access(agent, user_request="Flights?", justification="Find", query="from:united.com")
    work_only = await broker.request_access(agent, user_request="Work flights?", justification="Find", query="from:united.com", account=WORK)
    ids = await _ids()
    async with client() as c:
        await c.post(f"/admin/connections/{ids[WORK]}/pause")
        status = lambda g: db.one("SELECT status FROM grants WHERE id = ?", g["grant_id"])  # noqa: E731
        assert (await status(work_only))["status"] == "revoked"
        assert (await status(every))["status"] == "active", "it still has the home inbox"
        found = (await broker.gmail_search(agent, every["grant_token"]))["messages"]
        assert [m["to"] for m in found] == [HOME]
        await c.post(f"/admin/connections/{ids[WORK]}/resume")


async def test_reconnecting_an_account_replaces_only_that_account():
    before = await accounts.of(USER, "gmail")
    await accounts.save(USER, "gmail", "google", HOME, "fresh")
    after = await accounts.of(USER, "gmail")
    assert [r["account"] for r in after] == [r["account"] for r in before]


def test_adding_another_google_account_shows_the_account_picker():
    url = google_oauth.connect_url({"id": USER, "email": HOME}, "gmail", another=True)
    q = parse_qs(urlsplit(url).query)
    assert q["prompt"] == ["select_account consent"] and "login_hint" not in q
