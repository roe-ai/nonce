"""OAuth 2.1 for the MCP endpoint, so ChatGPT, Claude and other clients connect with a URL.

The MCP SDK serves the protocol (metadata, dynamic client registration, /authorize, /token,
/revoke, PKCE, and the 401 that points clients at the metadata). This module stores clients,
codes and tokens, and sends /authorize to the dashboard, where the signed-in user approves.
Approving makes the client one of the user's AI apps; its tokens act as that app.
Static `privato_agent_` keys (and `valet_agent_`, `nonce_agent_` and `pvt_agent_` ones from earlier names) keep working for clients that can send a header.
"""

import secrets
from typing import Any
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from . import db
from .config import settings
from .crypto import hash_token, new_token
from .errors import AccessError

ACCESS_TTL_S = 3600
REFRESH_TTL_S = 90 * 86400
CODE_TTL_S = 300
REQUEST_TTL_S = 900


def resource_url() -> str:
    return f"{settings().public_url.rstrip('/')}/mcp"


def _our_resource(resource: str) -> bool:
    return resource.rstrip("/") in {f"{u.rstrip('/')}/mcp" for u in [settings().public_url, *settings().old_public_urls]}


def guess_kind(client: OAuthClientInformationFull) -> str:
    """Which known app this client is, for its logo and name in the dashboard."""
    hay = " ".join([client.client_name or "", *(str(u) for u in client.redirect_uris or []), str(client.client_uri or "")]).lower()
    for needle, kind in (
        ("chatgpt", "chatgpt"),
        ("openai", "chatgpt"),
        ("claude", "claude"),
        ("anthropic", "claude"),
        ("cursor", "cursor"),
        ("gemini", "gemini"),
        ("copilot", "copilot"),
        ("perplexity", "perplexity"),
        ("windsurf", "windsurf"),
        ("codex", "codex"),
    ):
        if needle in hay:
            return kind
    return "custom"


def display_name(client: OAuthClientInformationFull) -> str:
    if client.client_name:
        return client.client_name[:60]
    uri = next(iter(client.redirect_uris or []), None)
    return (urlparse(str(uri)).hostname or "An app") if uri else "An app"


async def _issue(client_id: str, agent_id: str, scopes: list[str], resource: str | None, family: str) -> OAuthToken:
    access, refresh = new_token("privato_at"), new_token("privato_rt")
    now = db.now()
    for token, kind, ttl in ((access, "access", ACCESS_TTL_S), (refresh, "refresh", REFRESH_TTL_S)):
        await db.insert(
            "oauth_tokens",
            {
                "token_hash": hash_token(token),
                "kind": kind,
                "client_id": client_id,
                "agent_id": agent_id,
                "family": family,
                "scopes": scopes,
                "resource": resource,
                "expires_at": now + ttl,
                "created_at": now,
            },
        )
    return OAuthToken(access_token=access, expires_in=ACCESS_TTL_S, refresh_token=refresh, scope=" ".join(scopes) or None)


async def _token_row(token: str, kind: str) -> dict | None:
    row = await db.one(
        """SELECT t.*, a.user_id FROM oauth_tokens t JOIN agents a ON a.id = t.agent_id
        WHERE t.token_hash = ? AND t.kind = ? AND t.revoked_at IS NULL AND t.expires_at > ? AND a.status = 'active'""",
        hash_token(token),
        kind,
        db.now(),
    )
    return row


async def agent_for_access_token(token: str) -> dict | None:
    row = await _token_row(token, "access")
    return await db.one("SELECT * FROM agents WHERE id = ?", row["agent_id"]) if row else None


async def revoke_agent_tokens(agent_id: str) -> None:
    await db.q("UPDATE oauth_tokens SET revoked_at = ? WHERE agent_id = ? AND revoked_at IS NULL", db.now(), agent_id)


class PrivatoOAuthProvider:
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = await db.one("SELECT info FROM oauth_clients WHERE client_id = ?", client_id)
        return OAuthClientInformationFull.model_validate_json(row["info"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await db.insert(
            "oauth_clients",
            {"client_id": client_info.client_id, "info": client_info.model_dump_json(exclude_none=True), "created_at": db.now()},
        )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and not _our_resource(params.resource):
            raise AuthorizeError("invalid_target", f"This server only issues tokens for {resource_url()}")
        request_id = secrets.token_urlsafe(24)
        await db.insert(
            "oauth_requests",
            {"id": request_id, "client_id": client.client_id, "params": params.model_dump_json(), "created_at": db.now()},
        )
        return f"{settings().dashboard_url.rstrip('/')}/connect?request={request_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        row = await db.one(
            "SELECT * FROM oauth_codes WHERE code_hash = ? AND client_id = ? AND used = 0", hash_token(authorization_code), client.client_id
        )
        if not row:
            return None
        params = AuthorizationParams.model_validate_json(row["params"])
        return AuthorizationCode(
            code=authorization_code,
            scopes=params.scopes or [],
            expires_at=row["expires_at"],
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=row["agent_id"],
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        code_hash = hash_token(authorization_code.code)
        row = await db.one("SELECT agent_id, used FROM oauth_codes WHERE code_hash = ?", code_hash)
        if not row or row["used"]:
            raise TokenError("invalid_grant", "Authorization code already used")
        await db.q("UPDATE oauth_codes SET used = 1 WHERE code_hash = ?", code_hash)
        return await _issue(client.client_id, row["agent_id"], authorization_code.scopes, authorization_code.resource, db.new_id())

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = await _token_row(refresh_token, "refresh")
        if not row or row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=row["scopes"],
            expires_at=int(row["expires_at"]),
            resource=row["resource"],
            subject=row["agent_id"],
        )

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        row = await _token_row(refresh_token.token, "refresh")
        if not row:
            raise TokenError("invalid_grant", "Refresh token is no longer valid")
        # Rotate: the old refresh token and its access tokens stop working.
        await db.q("UPDATE oauth_tokens SET revoked_at = ? WHERE family = ? AND revoked_at IS NULL", db.now(), row["family"])
        return await _issue(client.client_id, row["agent_id"], scopes or row["scopes"], row["resource"], row["family"])

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token.startswith(("privato_agent_", "valet_agent_", "nonce_agent_", "pvt_agent_")):
            agent = await db.one("SELECT id, user_id, status FROM agents WHERE key_hash = ?", hash_token(token))
            if not agent or agent["status"] != "active":
                return None
            return AccessToken(token=token, client_id=f"agent:{agent['id']}", scopes=[], subject=agent["id"])
        row = await _token_row(token, "access")
        if not row or (row["resource"] and not _our_resource(row["resource"])):
            return None
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=int(row["expires_at"]),
            resource=row["resource"],
            subject=row["agent_id"],
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        row = await db.one("SELECT family FROM oauth_tokens WHERE token_hash = ?", hash_token(token.token))
        if row:
            await db.q("UPDATE oauth_tokens SET revoked_at = ? WHERE family = ? AND revoked_at IS NULL", db.now(), row["family"])


provider = PrivatoOAuthProvider()


# ---------------------------------------------------------------------------
# Consent, called by the dashboard for the signed-in user


async def _pending(request_id: str) -> tuple[dict, OAuthClientInformationFull, AuthorizationParams]:
    row = await db.one("SELECT * FROM oauth_requests WHERE id = ?", request_id)
    if not row or row["status"] != "pending" or db.now() - row["created_at"] > REQUEST_TTL_S:
        raise AccessError("request_expired", "This connection request expired. Start again from the app.", 404)
    client = await provider.get_client(row["client_id"])
    if not client:
        raise AccessError("request_expired", "This app is no longer registered. Start again from the app.", 404)
    return row, client, AuthorizationParams.model_validate_json(row["params"])


async def describe_request(request_id: str) -> dict[str, Any]:
    _, client, params = await _pending(request_id)
    return {
        "client_name": display_name(client),
        "kind": guess_kind(client),
        "redirect_host": urlparse(str(params.redirect_uri)).hostname,
    }


async def approve_request(user: dict, request_id: str) -> str:
    row, client, params = await _pending(request_id)
    await db.update("oauth_requests", request_id, status="approved")
    agent = await db.one(
        "SELECT * FROM agents WHERE user_id = ? AND oauth_client_id = ? ORDER BY created_at DESC LIMIT 1", user["id"], client.client_id
    )
    if agent:
        await db.update("agents", agent["id"], status="active")
    else:
        agent = await db.insert(
            "agents",
            {
                "user_id": user["id"],
                "name": display_name(client),
                "kind": guess_kind(client),
                # OAuth apps have no static key; this placeholder can't be presented as one.
                "key_hash": hash_token(new_token("privato_oauth_placeholder")),
                "key_prefix": "oauth",
                "status": "active",
                "created_at": db.now(),
                "oauth_client_id": client.client_id,
            },
        )
    code = secrets.token_urlsafe(32)
    await db.insert(
        "oauth_codes",
        {
            "code_hash": hash_token(code),
            "client_id": client.client_id,
            "agent_id": agent["id"],
            "params": row["params"],
            "expires_at": db.now() + CODE_TTL_S,
        },
    )
    return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)


async def deny_request(request_id: str) -> str:
    _, _, params = await _pending(request_id)
    await db.update("oauth_requests", request_id, status="denied")
    return construct_redirect_uri(
        str(params.redirect_uri), error="access_denied", error_description="The user declined", state=params.state
    )
