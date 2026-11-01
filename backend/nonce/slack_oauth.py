"""Connect Slack: OAuth v2 for a user token with read-only search and history scopes.

Slack redirects to {DASHBOARD_URL}/oauth/slack, which hands the code back here.
The token is stored encrypted; agents never see it.
"""

import json
import secrets
from urllib.parse import urlencode

import httpx

from . import accounts
from .config import settings
from .crypto import encrypt
from .errors import AccessError
from .google_oauth import _check_state, _state

USER_SCOPES = "search:read,channels:history,groups:history,im:history,mpim:history"


def redirect_uri() -> str:
    return f"{settings().dashboard_url.rstrip('/')}/oauth/slack"


def connect_url(user: dict) -> str:
    s = settings()
    if not (s.slack_client_id and s.slack_client_secret):
        raise AccessError("not_configured", "Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET in backend/.env", 409)
    params = {
        "client_id": s.slack_client_id,
        "user_scope": USER_SCOPES,
        "redirect_uri": redirect_uri(),
        "state": _state("slack", user["id"], secrets.token_hex(8)),
    }
    return f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"


async def complete_connect(user: dict, code: str, state: str) -> dict:
    parts = state.split(".")
    _check_state(state, "slack", user["id"], parts[2] if len(parts) == 5 else "")
    s = settings()
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={"code": code, "redirect_uri": redirect_uri()},
            auth=(s.slack_client_id or "", s.slack_client_secret or ""),
        )
    body = res.json()
    authed = body.get("authed_user") or {}
    if not body.get("ok") or not authed.get("access_token"):
        raise AccessError("oauth_failed", f"Slack didn't connect: {body.get('error', 'no user token returned')}", 400)
    team = (body.get("team") or {}).get("name", "Slack")
    return await accounts.save(
        user["id"], "slack", "slack", team, encrypt(json.dumps({"access_token": authed["access_token"], "user_id": authed.get("id"), "team": team}))
    )
