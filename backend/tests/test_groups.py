import asyncio

import httpx

from privato import broker, db, groups, luna, sms, tasks
from privato.main import app
from privato.notify import review_link

from conftest import TEST_USER

ADMIN = {"Authorization": "Bearer test-admin", "X-Privato-User": TEST_USER}
TRIP = "Plan my Tokyo trip next week"


def client(user_id: str = TEST_USER) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={**ADMIN, "X-Privato-User": user_id})


def g(id_, question, at, agent="a", task=None, category="travel"):
    return {"id": id_, "agent_id": agent, "user_request": question, "created_at": at, "task_id": task, "category": category}


def test_groups_one_apps_requests_for_one_task_but_never_login_codes():
    pending = [
        g("1", TRIP, 0),
        g("2", "plan my tokyo trip next week", 5),
        g("3", "What's the weather in Paris?", 6),
        g("4", TRIP, 7, agent="b"),
        g("5", TRIP, 8, category="security"),
        g("6", "Find the itinerary doc", 9, task="t1"),
        g("7", "Free evenings on my calendar", 10, task="t1"),
        g("8", TRIP, 5000),
    ]
    found = {tuple(m["id"] for m in grp) for grp in groups.group(pending)}
    assert found == {("1", "2"), ("3",), ("4",), ("5",), ("6", "7"), ("8",)}
    assert [m["id"] for m in groups.group_of("2", pending)] == ["1", "2"]


async def ask(agent, question, src, query):
    return await broker.request_access(agent, user_request=question, justification="Plan the trip", query=query, source=src)


async def test_parallel_requests_for_one_task_share_one_text_one_click_and_one_stop(agent, detector, monkeypatch):
    await db.q("UPDATE users SET phone = '+14155550100', phone_verified_at = ? WHERE id = ?", db.now(), TEST_USER)
    sent = []

    async def fake_send(phone, body):
        sent.append(body)
        return True

    monkeypatch.setattr(sms, "send_text", fake_send)
    detector.access_signals["user_initiated"] = 0.05
    mail, cal, files = await asyncio.gather(
        ask(agent, TRIP, "gmail", "from:united.com Tokyo"),
        ask(agent, TRIP, "calendar", "Tokyo"),
        ask(agent, TRIP, "drive", "name:itinerary"),
    )
    assert {mail["status"], cal["status"], files["status"]} == {"pending"}
    assert len(sent) == 1, "one text for the whole task"
    ids = [mail["grant_id"], cal["grant_id"], files["grant_id"]]
    rows = await db.q(f"SELECT task_id FROM grants WHERE id IN ({', '.join('?' * 3)})", *ids)
    assert len({r["task_id"] for r in rows}) == 1

    async with client() as c:
        mine = [grp for grp in (await c.get("/admin/requests")).json() if grp["grants"][0]["agent_id"] == agent["id"]]
        assert len(mine) == 1 and mine[0]["title"] == TRIP.rstrip("?")
        assert {x["id"] for x in mine[0]["grants"]} == set(ids)

        assert (await c.post("/admin/requests/approve", json={"grant_ids": ids[:2]})).json()["done"] == ids[:2]
        assert (await db.one("SELECT status FROM grants WHERE id = ?", ids[2]))["status"] == "pending", "only what you saw"
        assert (await c.post("/admin/requests/revoke", json={"grant_ids": ids[:2]})).json()["done"] == ids[:2]
        assert (await c.post("/admin/requests/deny", json={"grant_ids": [ids[2], "nope"]})).status_code == 404


async def test_text_page_allows_the_whole_group(agent, detector):
    detector.access_signals["user_initiated"] = 0.05
    first = await ask(agent, "Get ready for my dentist appointment", "gmail", "from:smiledental.com")
    second = await ask(agent, "Get ready for my dentist appointment", "calendar", "dentist")
    path = review_link(first["grant_id"]).split("://", 1)[1].split("/", 1)[1]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        page = (await c.get(f"/{path}")).text
        assert "read your email and see your calendar" in page and "Allow all 2" in page
        done = await c.post(f"/{path}", data={"action": "approve", "grant": [first["grant_id"], second["grant_id"]]})
        assert "Allowed" in done.text
    statuses = await db.q("SELECT status FROM grants WHERE id IN (?, ?)", first["grant_id"], second["grant_id"])
    assert [s["status"] for s in statuses] == ["active", "active"]


async def test_luna_names_tasks_and_folds_a_follow_up_into_the_task_it_continues(agent, detector, monkeypatch):
    answers = []

    async def fake_run(name, instructions, task, output_type, tools=None, max_turns=1):
        answers.append(task)
        return answers_for.pop(0)

    monkeypatch.setattr(luna, "configured", lambda: True)
    monkeypatch.setattr(luna, "run", fake_run)
    answers_for = [tasks.Placement(task_id=None, title='  "Tokyo trip"  ')]
    first = await ask(agent, "When does my flight to Tokyo leave?", "gmail", "from:united.com")
    t1 = (await db.one("SELECT task_id FROM grants WHERE id = ?", first["grant_id"]))["task_id"]
    assert (await db.one("SELECT title, placed_by FROM tasks WHERE id = ?", t1)) == {"title": "Tokyo trip", "placed_by": "luna"}

    answers_for = [tasks.Placement(task_id=t1[:8], title="Boarding")]
    follow = await ask(agent, "What time do I board my plane?", "calendar", "boarding")
    assert (await db.one("SELECT task_id FROM grants WHERE id = ?", follow["grant_id"]))["task_id"] == t1
    assert "When does my flight to Tokyo leave?" in answers[-1], "Luna sees the recent task's questions"

    answers_for = [tasks.Placement(task_id="made-up", title="x" * 200)]
    other = await ask(agent, "Summarize my newsletters", "gmail", "category:promotions")
    t3 = (await db.one("SELECT task_id FROM grants WHERE id = ?", other["grant_id"]))["task_id"]
    title = (await db.one("SELECT title FROM tasks WHERE id = ?", t3))["title"]
    assert t3 != t1 and len(title) <= tasks.TITLE_MAX
