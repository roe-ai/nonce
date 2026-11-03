"""Google OAuth for two things: signing in to Privato, and connecting Gmail, Calendar or Drive.

Both redirect to the dashboard root (the one URI registered with Google), which hands
the code back here. The `state` prefix tells the dashboard which flow it is.
Privato stores the refresh tokens encrypted; agents never see them.
"""

import json
import secrets
import time
from urllib.parse import urlencode

import httpx

from . import accounts, db
from .config import settings
from .crypto import encrypt, sign, verify
from .errors import AccessError
from .providers.google import SCOPES as GOOGLE_SCOPES

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
LOGIN_SCOPE = "openid email profile"
STATE_TTL_S = 900


def _redirect_uri() -> str:
    s = settings()
    return s.google_redirect_uri or s.dashboard_url


def _require_config() -> None:
    s = settings()
    if not (s.google_client_id and s.google_client_secret):
        raise AccessError("not_configured", "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env", 409)


def _url(scope: str, state: str, **extra: str) -> str:
    _require_config()
    params = {"client_id": settings().google_client_id, "redirect_uri": _redirect_uri(), "response_type": "code", "scope": scope, "state": state, **extra}
    return f"{AUTH_URL}?{urlencode(params)}"


def _check_state(state: str, flow: str, *bound: str) -> None:
    """State is `<flow>.<bound...>.<issued>.<sig>`; `bound` are values the caller must match."""
    parts = state.split(".")
    if len(parts) != len(bound) + 3 or parts[0] != flow or parts[1:-2] != list(bound):
        raise AccessError("bad_state", "This sign-in link doesn't belong to you. Please try again.", 400)
    issued, sig = parts[-2], parts[-1]
    if not verify(sig, flow, *bound, issued) or not issued.isdigit() or time.time() - int(issued) > STATE_TTL_S:
        raise AccessError("bad_state", "This sign-in link expired. Please try again.", 400)


def _state(flow: str, *bound: str) -> str:
    issued = str(int(time.time()))
    return ".".join([flow, *bound, issued, sign(flow, *bound, issued)])


async def _exchange(client: httpx.AsyncClient, code: str) -> dict:
    s = settings()
    res = await client.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        },
    )
    if res.status_code != 200:
        raise AccessError("oauth_failed", f"Google rejected the sign-in: {res.json().get('error_description', res.text)}", 400)
    return res.json()


# ---------------------------------------------------------------------------
# Sign in / create account


def login_url(nonce: str) -> str:
    """`nonce` is also kept in a cookie by the dashboard, so a login can only finish in the browser that started it."""
    if not nonce or "." in nonce:
        raise AccessError("bad_request", "Missing login nonce", 400)
    return _url(LOGIN_SCOPE, _state("login", nonce), prompt="select_account")


async def complete_login(code: str, state: str, nonce: str) -> dict:
    _check_state(state, "login", nonce)
    async with httpx.AsyncClient(timeout=15) as client:
        tokens = await _exchange(client, code)
        info = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        info.raise_for_status()
    profile = info.json()
    if not profile.get("email_verified"):
        raise AccessError("unverified_email", "Your Google account's email isn't verified", 400)

    now = db.now()
    user = await db.one("SELECT * FROM users WHERE google_sub = ?", profile["sub"])
    if user:
        await db.update("users", user["id"], email=profile["email"], name=profile.get("name"), picture=profile.get("picture"), last_login_at=now)
        return {**user, "email": profile["email"], "name": profile.get("name"), "picture": profile.get("picture"), "created": False}

    first = not await db.one("SELECT 1 AS ok FROM users LIMIT 1")
    user = await db.insert(
        "users",
        {
            "google_sub": profile["sub"],
            "email": profile["email"],
            "name": profile.get("name"),
            "picture": profile.get("picture"),
            "created_at": now,
            "last_login_at": now,
        },
    )
    if first:
        # Whoever ran Privato before accounts existed keeps their apps and connections.
        await db.q("UPDATE agents SET user_id = ? WHERE user_id IS NULL", user["id"])
        await db.q("UPDATE connections SET user_id = ? WHERE user_id IS NULL", user["id"])
    return {**user, "created": True}


# ---------------------------------------------------------------------------
# Connect Gmail, Calendar or Drive (one read-only scope each, one connection each)

GOOGLE_PROVIDERS = ("gmail", "calendar", "drive")
# Who the account belongs to, and proof the API is enabled for this Google project.
PROBES = {
    "gmail": ("https://gmail.googleapis.com/gmail/v1/users/me/profile", lambda j: j["emailAddress"]),
    "calendar": ("https://www.googleapis.com/calendar/v3/calendars/primary", lambda j: j["id"]),
    "drive": ("https://www.googleapis.com/drive/v3/about?fields=user", lambda j: j["user"]["emailAddress"]),
}
API_NAMES = {"gmail": "Gmail API", "calendar": "Google Calendar API", "drive": "Google Drive API"}


def connect_url(user: dict, provider: str, another: bool = False) -> str:
    """`another`: let the user pick a different Google account than the one they signed in with."""
    hint = {} if another else {"login_hint": user["email"]}
    return _url(
        GOOGLE_SCOPES[provider],
        _state(provider, user["id"], secrets.token_hex(8)),
        access_type="offline",
        prompt="select_account consent" if another else "consent",
        **hint,
    )


async def complete_connect(user: dict, code: str, state: str) -> dict:
    parts = state.split(".")
    provider = parts[0]
    if provider not in GOOGLE_PROVIDERS:
        raise AccessError("bad_state", "This sign-in link doesn't belong to you. Please try again.", 400)
    _check_state(state, provider, user["id"], parts[2] if len(parts) == 5 else "")
    url, account_of = PROBES[provider]
    async with httpx.AsyncClient(timeout=15) as client:
        tokens = await _exchange(client, code)
        probe = await client.get(url, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        if probe.status_code != 200:
            raise AccessError(
                "provider_unavailable", f"Google didn't let us in. Make sure the {API_NAMES[provider]} is enabled for this app.", 400
            )
    if "refresh_token" not in tokens:
        raise AccessError("no_refresh_token", "Google returned no refresh token; remove Privato from your Google account and reconnect", 400)
    return await accounts.save(
        user["id"], provider, "google", account_of(probe.json()), encrypt(json.dumps({"refresh_token": tokens["refresh_token"]}))
    )
