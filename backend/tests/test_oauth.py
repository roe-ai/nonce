import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx

from privato import broker
from privato.config import settings
from privato.main import app
from privato.mcp_server import mcp
from privato.oauth import PrivatoOAuthProvider

from conftest import TEST_USER

BASE = "http://localhost:8000"
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
ADMIN = {"Authorization": "Bearer test-admin", "X-Privato-User": TEST_USER}


def http() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def connect(c: httpx.AsyncClient) -> tuple[str, dict]:
    """Register like ChatGPT, approve on the dashboard, exchange the code. Returns (client_id, tokens)."""
    reg = await c.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT],
            "client_name": "ChatGPT",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]
    verifier, challenge = pkce()
    auth = await c.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st8",
            "resource": f"{BASE}/mcp",
        },
    )
    assert auth.status_code == 302, auth.text
    consent = urlparse(auth.headers["location"])
    assert consent.path == "/connect"
    request_id = parse_qs(consent.query)["request"][0]

    shown = (await c.get(f"/admin/oauth/requests/{request_id}", headers=ADMIN)).json()
    assert shown["client_name"] == "ChatGPT" and shown["kind"] == "chatgpt"
    back = urlparse((await c.post(f"/admin/oauth/requests/{request_id}/approve", headers=ADMIN)).json()["redirect_to"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT
    q = parse_qs(back.query)
    assert q["state"] == ["st8"]

    form = {
        "grant_type": "authorization_code",
        "code": q["code"][0],
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": f"{BASE}/mcp",
    }
    tokens = await c.post("/token", data=form)
    assert tokens.status_code == 200, tokens.text
    assert (await c.post("/token", data=form)).status_code == 400, "codes are single-use"
    return client_id, tokens.json()


async def test_discovery_and_401_point_clients_at_oauth():
    async with http() as c:
        res = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert res.status_code == 401
        assert "/.well-known/oauth-protected-resource/mcp" in res.headers["www-authenticate"]
        prm = (await c.get("/.well-known/oauth-protected-resource/mcp")).json()
        assert prm["resource"] == f"{BASE}/mcp"
        assert [s.rstrip("/") for s in prm["authorization_servers"]] == [BASE]
        meta = (await c.get("/.well-known/oauth-authorization-server")).json()
        assert meta["registration_endpoint"].endswith("/register") and "S256" in meta["code_challenge_methods_supported"]


async def test_chatgpt_connects_and_acts_as_the_users_app(detector):
    async with http() as c:
        _, tokens = await connect(c)
    agent = await broker.authenticate(tokens["access_token"])
    assert agent["user_id"] == TEST_USER and agent["kind"] == "chatgpt" and agent["name"] == "ChatGPT"
    g = await broker.request_access(
        agent, user_request="When does my flight leave?", justification="Airline email", query="from:united.com Tokyo OR NRT"
    )
    assert g["status"] == "active"


async def test_oauth_token_works_on_the_mcp_endpoint():
    async with http() as c, mcp.session_manager.run():
        _, tokens = await connect(c)
        res = await c.post(
            "/mcp",
            headers={"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
            },
        )
        assert res.status_code == 200, res.text


async def test_refresh_rotates_and_removing_the_app_cuts_it_off():
    async with http() as c:
        client_id, tokens = await connect(c)
        fresh = await c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
        assert fresh.status_code == 200, fresh.text
        new = fresh.json()
        old = await c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
        assert old.status_code == 400
        try:
            await broker.authenticate(tokens["access_token"])
            raise AssertionError("old access token still works")
        except Exception as e:
            assert getattr(e, "code", None) == "unauthenticated"

        agent = await broker.authenticate(new["access_token"])
        assert (await c.post(f"/admin/agents/{agent['id']}/disable", headers=ADMIN)).status_code == 200
        try:
            await broker.authenticate(new["access_token"])
            raise AssertionError("token survived removing the app")
        except Exception as e:
            assert getattr(e, "code", None) == "unauthenticated"


async def test_declining_sends_access_denied_back():
    async with http() as c:
        reg = await c.post("/register", json={"redirect_uris": [REDIRECT], "client_name": "Claude", "token_endpoint_auth_method": "none"})
        _, challenge = pkce()
        auth = await c.get(
            "/authorize",
            params={"response_type": "code", "client_id": reg.json()["client_id"], "redirect_uri": REDIRECT, "code_challenge": challenge, "state": "s"},
        )
        request_id = parse_qs(urlparse(auth.headers["location"]).query)["request"][0]
        back = (await c.post(f"/admin/oauth/requests/{request_id}/deny", headers=ADMIN)).json()["redirect_to"]
        assert parse_qs(urlparse(back).query)["error"] == ["access_denied"]
        assert (await c.post(f"/admin/oauth/requests/{request_id}/approve", headers=ADMIN)).status_code == 404


async def test_moving_the_public_url_keeps_apps_connected_through_old_urls(monkeypatch):
    async with http() as c:
        _, tokens = await connect(c)
    s = settings()
    monkeypatch.setattr(s, "public_url", "https://api.privato.example")
    provider = PrivatoOAuthProvider()
    assert await provider.load_access_token(tokens["access_token"]) is None
    monkeypatch.setattr(s, "old_public_urls", [BASE])
    assert await provider.load_access_token(tokens["access_token"]) is not None
