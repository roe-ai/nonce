import hmac
from html import escape
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import accounts, broker, connectors, db, google_oauth, groups, oauth, similar, slack_oauth, sms, webpush
from .config import settings
from .crypto import verify
from .errors import AccessError
from .mcp_server import mcp, mcp_app
from .signals import configured as signals_configured
from .humanize import describe_filter
from .policy import MODES, AccessContext, decide_access, human_duration, is_offline
from .sources import SOURCES, source

logging.basicConfig(level=logging.INFO)

_mcp_asgi = mcp_app()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.migrate()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Privato", lifespan=lifespan)


@app.exception_handler(AccessError)
async def access_error(_: Request, e: AccessError):
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


@app.get("/health")
async def health():
    s = settings()
    return {"ok": True, "signals": signals_configured(), "db": "turso" if s.turso_database_url else "local"}


# ---------------------------------------------------------------------------
# Agent REST API (same operations as the MCP tools)


async def current_agent(authorization: str | None = Header(None)) -> dict:
    return await broker.authenticate((authorization or "").removeprefix("Bearer ").strip() or None)


SourceId = Literal["gmail", "calendar", "drive", "slack"]


class AccessRequest(BaseModel):
    user_request: str
    justification: str
    query: str
    source: str = Field("gmail", description='gmail, calendar, drive, slack, or a connector id ("connector:…") from GET /v1/sources')
    scopes: list[str] | None = None
    duration_minutes: int = Field(10, ge=1)
    account: list[str] | str | None = None


class GrantRef(BaseModel):
    grant_token: str


class SearchRequest(GrantRef):
    query: str = ""
    max_results: int = Field(10, ge=1, le=25)


class ReadRequest(GrantRef):
    item_id: str | None = None
    message_id: str | None = None  # older Gmail clients


class ConnectorCall(GrantRef):
    tool: str
    arguments: dict | None = None


v1 = APIRouter(prefix="/v1")


@v1.post("/access")
async def v1_request_access(body: AccessRequest, agent: dict = Depends(current_agent)):
    return await broker.request_access(agent, **body.model_dump())


@v1.get("/sources")
async def v1_sources(agent: dict = Depends(current_agent)):
    return await broker.list_sources(agent)


@v1.post("/connectors/call")
async def v1_connector_call(body: ConnectorCall, agent: dict = Depends(current_agent)):
    return await broker.connector_call(agent, body.grant_token, body.tool, body.arguments)


@v1.post("/access/check")
async def v1_check_access(body: GrantRef, agent: dict = Depends(current_agent)):
    return await broker.check_access(agent, body.grant_token)


@v1.post("/{source_id}/search")
async def v1_search(source_id: SourceId, body: SearchRequest, agent: dict = Depends(current_agent)):
    return await broker.search(agent, source_id, body.grant_token, body.query, body.max_results)


@v1.post("/{source_id}/read")
async def v1_read(source_id: SourceId, body: ReadRequest, agent: dict = Depends(current_agent)):
    item_id = body.item_id or body.message_id
    if not item_id:
        raise AccessError("bad_request", "item_id is required", 400)
    return await broker.read(agent, source_id, body.grant_token, item_id)


app.include_router(v1)


# ---------------------------------------------------------------------------
# Dashboard API (server-to-server from the Next.js app, admin token)


async def require_admin(authorization: str | None = Header(None)) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings().privato_admin_token):
        raise AccessError("unauthenticated", "Admin token required", 401)


async def current_user(x_privato_user: str | None = Header(None), x_valet_user: str | None = Header(None), x_nonce_user: str | None = Header(None), x_privaty_user: str | None = Header(None)) -> dict:
    """The dashboard server names the signed-in user; only it holds the admin token."""
    user = await db.one("SELECT * FROM users WHERE id = ?", x_privato_user or x_valet_user or x_nonce_user or x_privaty_user or "")
    if not user:
        raise AccessError("unauthenticated", "Sign in required", 401)
    return user


admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
User = Annotated[dict, Depends(current_user)]

# Everything a user owns hangs off their agents and connections.
OWNED_AGENTS = "SELECT id FROM agents WHERE user_id = ?"

GRANT_COLUMNS = """g.id, g.agent_id, a.name AS agent_name, a.kind AS agent_kind, g.source, g.status, g.scopes,
    g.query_constraint, g.justification, g.user_request, g.category, g.ttl_s, g.max_calls, g.calls_used,
    g.decided_by, g.reason, g.signals, g.created_at, g.activated_at, g.expires_at, g.ended_at, g.task_id, t.title AS task_title, g.account, g.account_ids"""
GRANTS = "grants g JOIN agents a ON a.id = g.agent_id LEFT JOIN tasks t ON t.id = g.task_id"


async def _owned(sql: str, *params: object) -> None:
    if not await db.one(sql, *params):
        raise AccessError("not_found", "Not found", 404)


async def _expire_due() -> None:
    now = db.now()
    await db.q("UPDATE grants SET status = 'expired', ended_at = expires_at WHERE status = 'active' AND expires_at <= ?", now)


def _public_user(user: dict) -> dict:
    start, end = broker.offline_hours(user)
    return {
        **{k: user.get(k) for k in ("id", "email", "name", "picture", "phone", "phone_verified_at", "created_at")},
        "offline_start": start,
        "offline_end": end,
        "timezone": user.get("timezone") or settings().timezone,
    }


# --- Sign in ---------------------------------------------------------------


@admin.get("/auth/google")
async def auth_google_url(nonce: str):
    return {"url": google_oauth.login_url(nonce)}


class LoginCode(BaseModel):
    code: str
    state: str
    nonce: str


@admin.post("/auth/google/complete")
async def auth_google_complete(body: LoginCode):
    user = await google_oauth.complete_login(body.code, body.state, body.nonce)
    return {**_public_user(user), "created": user["created"]}


@admin.get("/me")
async def me(user: User):
    return _public_user(user)


# --- Phone (Twilio Verify) ---------------------------------------------------

PHONE_RESEND_S = 30


class PhoneNumber(BaseModel):
    phone: str


class PhoneCode(BaseModel):
    code: str


def _texting_on() -> None:
    if not sms.enabled():
        raise AccessError("not_found", "Texting is turned off on this server", 404)


@admin.post("/me/phone")
async def start_phone(body: PhoneNumber, user: User):
    _texting_on()
    phone = sms.normalize_phone(body.phone)
    if not phone:
        raise AccessError("bad_phone", "Enter a phone number with its area code, like (415) 555-0100.", 400)
    wait = PHONE_RESEND_S - (db.now() - (user["phone_code_sent_at"] or 0))
    if user["phone_pending"] == phone and wait > 0:
        raise AccessError("too_soon", f"Please wait {int(wait) + 1} seconds before asking for another code.", 429)
    if error := await sms.send_code(phone):
        raise AccessError("sms_failed", error, 400)
    await db.update("users", user["id"], phone_pending=phone, phone_code_sent_at=db.now())
    return {"ok": True, "phone": phone, "mode": sms.verify_mode()}


@admin.post("/me/phone/verify")
async def verify_phone(body: PhoneCode, user: User):
    _texting_on()
    phone = user["phone_pending"]
    if not phone or not await sms.check_code(phone, body.code.strip()):
        raise AccessError("bad_code", "That code didn't work. Check it, or send a new one.", 400)
    await db.update("users", user["id"], phone=phone, phone_verified_at=db.now(), phone_pending=None)
    return _public_user({**user, "phone": phone, "phone_verified_at": db.now()})


@admin.delete("/me/phone")
async def remove_phone(user: User):
    await db.update("users", user["id"], phone=None, phone_verified_at=None, phone_pending=None)
    return {"ok": True}


class OfflineHours(BaseModel):
    start: int = Field(ge=0, le=23)
    end: int = Field(ge=0, le=23)
    timezone: str | None = None


@admin.put("/me/offline")
async def set_offline(body: OfflineHours, user: User):
    tz = body.timezone or user.get("timezone")
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise AccessError("bad_timezone", f"Unknown timezone {tz}", 400) from None
    await db.update("users", user["id"], offline_start=body.start, offline_end=body.end, timezone=tz)
    return _public_user({**user, "offline_start": body.start, "offline_end": body.end, "timezone": tz})


@admin.get("/notifications")
async def notification_status(user: User):
    devices = await db.one("SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id = ?", user["id"])
    return {
        "sms": sms.enabled(),
        "verify": sms.verify_mode(),
        "messages": sms.message_mode(),
        "push_key": settings().vapid_public_key if webpush.configured() else None,
        "push_devices": devices["n"] if devices else 0,
    }


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscription(BaseModel):
    endpoint: str = Field(pattern=r"^https://", max_length=1000)
    keys: PushKeys
    device: str | None = Field(default=None, max_length=200)


class PushEndpoint(BaseModel):
    endpoint: str = Field(max_length=1000)


@admin.post("/push")
async def add_push(body: PushSubscription, user: User):
    if not webpush.configured():
        raise AccessError("push_off", "Push notifications aren't set up on this server.", 400)
    await webpush.subscribe(user["id"], body.endpoint, body.keys.p256dh, body.keys.auth, body.device)
    return {"ok": True}


@admin.post("/push/remove")
async def remove_push(body: PushEndpoint, user: User):
    await webpush.unsubscribe(user["id"], body.endpoint)
    return {"ok": True}


@admin.post("/push/test")
async def test_push(user: User):
    sent = await webpush.send(user["id"], title="Privato is on this phone", body="You'll get a notification here when an app needs your OK.", url="/")
    return {"sent": sent}


# --- Overview ----------------------------------------------------------------


@admin.get("/overview")
async def overview(user: User):
    await _expire_due()
    uid = user["id"]
    since = db.now() - 86400
    return await db.one(
        f"""SELECT
            (SELECT COUNT(*) FROM grants WHERE status = 'active' AND agent_id IN ({OWNED_AGENTS})) AS active_grants,
            (SELECT COUNT(*) FROM grants WHERE status = 'pending' AND agent_id IN ({OWNED_AGENTS})) AS pending,
            (SELECT COUNT(*) FROM alerts WHERE status = 'open' AND agent_id IN ({OWNED_AGENTS})) AS open_alerts,
            (SELECT COUNT(*) FROM agents WHERE status = 'active' AND user_id = ?) AS agents,
            (SELECT COUNT(*) FROM connections WHERE status = 'active' AND user_id = ?) AS connections,
            (SELECT COUNT(*) FROM events e LEFT JOIN grants g ON g.id = e.grant_id WHERE e.ts > ? AND {EVENT_OWNER}) AS events_24h,
            (SELECT COUNT(*) FROM events e LEFT JOIN grants g ON g.id = e.grant_id
                WHERE e.ts > ? AND e.decision IN ('deny', 'revoke', 'redact') AND {EVENT_OWNER}) AS blocked_24h""",
        uid,
        uid,
        uid,
        uid,
        uid,
        since,
        uid,
        since,
        uid,
    )


# --- Agents ------------------------------------------------------------------


@admin.get("/agents")
async def list_agents(user: User):
    return await db.q(
        """SELECT a.id, a.name, a.kind, a.key_prefix, a.status, a.mode, a.created_at, a.last_seen_at,
            (SELECT COUNT(*) FROM grants g WHERE g.agent_id = a.id AND g.status = 'active') AS active_grants,
            (SELECT COUNT(*) FROM events e WHERE e.agent_id = a.id AND e.decision IN ('deny', 'revoke')) AS blocked
        FROM agents a WHERE a.user_id = ? ORDER BY a.created_at DESC""",
        user["id"],
    )


AgentKind = Literal[
    "chatgpt", "claude", "cursor", "gemini", "copilot", "perplexity", "muse", "grok",
    "deepseek", "mistral", "meta", "pi", "codex", "windsurf", "manus", "custom",
]


class NewAgent(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: AgentKind = "custom"


@admin.post("/agents")
async def create_agent(body: NewAgent, user: User):
    row, key = await broker.create_agent(user["id"], body.name, body.kind)
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "key": key}


class AgentSettings(BaseModel):
    mode: Literal["cautious", "standard", "relaxed"]


@admin.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentSettings, user: User):
    await _owned("SELECT 1 AS ok FROM agents WHERE id = ? AND user_id = ?", agent_id, user["id"])
    await db.update("agents", agent_id, mode=body.mode)
    return {"ok": True, "mode": body.mode}


PREVIEW_DAYS = 30
FAMILIAR_LEXICAL = 0.35


@admin.get("/agents/{agent_id}/modes")
async def preview_modes(agent_id: str, user: User):
    """Replays this app's recent requests under each mode: how often each would have asked you.

    Uses the signals stored with each request. Where Cautious needs a familiarity read
    that wasn't taken, a close look-alike among your earlier questions stands in for it.
    """
    await _owned("SELECT 1 AS ok FROM agents WHERE id = ? AND user_id = ?", agent_id, user["id"])
    since = db.now() - PREVIEW_DAYS * 86400
    grants = await db.q(
        "SELECT * FROM grants WHERE agent_id = ? AND created_at > ? AND signals IS NOT NULL ORDER BY created_at",
        agent_id,
        since,
    )
    earlier = [
        r["user_request"]
        for r in await db.q(
            """SELECT g.user_request FROM grants g JOIN agents a ON a.id = g.agent_id
            WHERE a.user_id = ? AND g.activated_at IS NOT NULL AND g.created_at <= ? ORDER BY g.created_at DESC LIMIT 500""",
            user["id"],
            since,
        )
    ]
    out = {name: {"allow": 0, "ask": 0, "deny": 0} for name in MODES}
    seen_categories: set[str] = set()
    start, end = broker.offline_hours(user)
    tz = ZoneInfo(user.get("timezone") or settings().timezone)
    for g in grants:
        signals = dict(g["signals"])
        if "familiar" not in signals:
            best = similar.rank(g["user_request"], earlier, 1)
            signals["familiar"] = 1.0 if best and best[0][1] >= FAMILIAR_LEXICAL else 0.0
        hour = datetime.fromtimestamp(g["created_at"], tz).hour
        ctx = AccessContext(
            requests_last_hour=0,
            known_categories=set(seen_categories),
            offline=is_offline(hour, start, end),
            history_size=len(earlier),
        )
        for name, m in MODES.items():
            d = decide_access(
                src=source(g["source"]), mode=m, scopes=g["scopes"], constraint=g["query_constraint"], ttl_s=g["ttl_s"], signals=signals, ctx=ctx
            )
            out[name][d.outcome] += 1
        if g["activated_at"]:
            earlier.insert(0, g["user_request"])
            if g["category"]:
                seen_categories.add(g["category"])
    return {"days": PREVIEW_DAYS, "requests": len(grants), "modes": out}


@admin.post("/agents/{agent_id}/disable")
async def disable_agent(agent_id: str, user: User):
    await _owned("SELECT 1 AS ok FROM agents WHERE id = ? AND user_id = ?", agent_id, user["id"])
    await db.update("agents", agent_id, status="disabled")
    await oauth.revoke_agent_tokens(agent_id)
    for g in await db.q("SELECT id FROM grants WHERE agent_id = ? AND status IN ('active', 'pending')", agent_id):
        await broker.revoke(g["id"], "You disconnected this app", by="user")
    return {"ok": True}


# --- Connecting an app with OAuth (consent screen) ------------------------------


@admin.get("/oauth/requests/{request_id}")
async def oauth_request(request_id: str, user: User):
    return await oauth.describe_request(request_id)


@admin.post("/oauth/requests/{request_id}/{decision}")
async def oauth_decide(request_id: str, decision: Literal["approve", "deny"], user: User):
    if decision == "approve":
        return {"redirect_to": await oauth.approve_request(user, request_id)}
    return {"redirect_to": await oauth.deny_request(request_id)}


# --- Connections -------------------------------------------------------------


@admin.get("/connections")
async def list_connections(user: User):
    """Every account, on or paused, oldest first."""
    return await accounts.of(user["id"])


@admin.get("/connections/{provider}/connect")
async def connect_url(provider: SourceId, user: User, another: bool = False):
    if provider == "slack":
        return {"url": slack_oauth.connect_url(user)}
    return {"url": google_oauth.connect_url(user, provider, another=another)}


class OAuthCode(BaseModel):
    code: str
    state: str


@admin.post("/connections/{provider}/complete")
async def connect_complete(provider: SourceId, body: OAuthCode, user: User):
    if provider == "slack":
        conn = await slack_oauth.complete_connect(user, body.code, body.state)
    else:
        if not body.state.startswith(f"{provider}."):
            raise AccessError("bad_state", "This sign-in link doesn't belong to you. Please try again.", 400)
        conn = await google_oauth.complete_connect(user, body.code, body.state)
    return {"id": conn["id"], "provider": conn["provider"], "account": conn["account"]}


async def _end_grants(connection_id: str, reason: str) -> None:
    """For connectors, whose access always reads exactly one."""
    for g in await db.q("SELECT id FROM grants WHERE connection_id = ? AND status IN ('active', 'pending')", connection_id):
        await broker.revoke(g["id"], reason, by="user")


@admin.delete("/connections/{connection_id}")
async def remove_connection(connection_id: str, user: User):
    row = await accounts.remove(user["id"], connection_id)
    await broker.end_grants_without_accounts(user["id"], row["provider"], "You disconnected this account")
    return {"ok": True}


@admin.post("/connections/{connection_id}/{action}")
async def pause_connection(connection_id: str, action: Literal["pause", "resume"], user: User):
    row = await accounts.set_paused(user["id"], connection_id, action == "pause")
    if action == "pause":
        await broker.end_grants_without_accounts(user["id"], row["provider"], "You paused this account")
    return {"ok": True}


# --- Connectors: your own MCP servers and APIs ---------------------------------


class NewConnector(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: connectors.Kind = "mcp"
    url: str = Field(min_length=8, max_length=2000)
    auth_header: str | None = Field(None, max_length=100, pattern=r"^[A-Za-z0-9-]*$")
    auth_value: str | None = Field(None, max_length=4000)


class ToolRule(BaseModel):
    rule: connectors.Rule


@admin.get("/connectors")
async def list_connectors(user: User):
    return [connectors.public(r) for r in await connectors.for_user(user["id"])]


@admin.post("/connectors")
async def add_connector(body: NewConnector, user: User):
    row = await connectors.add(user["id"], **body.model_dump(), detector=broker.detector())
    return connectors.public(row)


@admin.post("/connectors/{connector_id}/refresh")
async def refresh_connector(connector_id: str, user: User):
    row = await connectors.refresh(await connectors.owned(user["id"], connector_id), broker.detector())
    return connectors.public(row)


@admin.put("/connectors/{connector_id}/tools/{tool}")
async def set_tool_rule(connector_id: str, tool: str, body: ToolRule, user: User):
    row = await connectors.set_rule(await connectors.owned(user["id"], connector_id), tool, body.rule)
    if body.rule == "off":
        for g in await db.q("SELECT id, scopes FROM grants WHERE connection_id = ? AND status IN ('active', 'pending')", connector_id):
            if tool in (g["scopes"] or []):
                await broker.revoke(g["id"], f"You turned off {tool}", by="user")
    return connectors.public(row)


@admin.post("/connectors/{connector_id}/{action}")
async def pause_connector(connector_id: str, action: Literal["pause", "resume"], user: User):
    await connectors.owned(user["id"], connector_id)
    await db.update("connectors", connector_id, status="paused" if action == "pause" else "active", updated_at=db.now())
    if action == "pause":
        await _end_grants(connector_id, "You paused this connector")
    return {"ok": True}


@admin.delete("/connectors/{connector_id}")
async def remove_connector(connector_id: str, user: User):
    await connectors.owned(user["id"], connector_id)
    await db.update("connectors", connector_id, status="removed", auth_enc=None, updated_at=db.now())
    await _end_grants(connector_id, "You removed this connector")
    return {"ok": True}


# --- Grants ------------------------------------------------------------------


@admin.get("/grants")
async def list_grants(user: User, status: str | None = None, limit: int = 100):
    await _expire_due()
    status_sql = "AND g.status = ?" if status else ""
    return await db.q(
        f"SELECT {GRANT_COLUMNS} FROM {GRANTS} WHERE a.user_id = ? {status_sql} ORDER BY g.created_at DESC LIMIT ?",
        *([user["id"], status] if status else [user["id"]]),
        limit,
    )


class GrantAccounts(BaseModel):
    connection_ids: list[str]


@admin.put("/grants/{grant_id}/accounts")
async def choose_grant_accounts(grant_id: str, body: GrantAccounts, user: User):
    return await broker.choose_accounts(user["id"], grant_id, body.connection_ids)


@admin.post("/grants/{grant_id}/{action}")
async def act_on_grant(grant_id: str, action: Literal["approve", "deny", "revoke"], user: User):
    await _owned("SELECT 1 AS ok FROM grants g JOIN agents a ON a.id = g.agent_id WHERE g.id = ? AND a.user_id = ?", grant_id, user["id"])
    if action == "approve":
        await broker.approve(grant_id, by="user")
    elif action == "deny":
        await broker.deny(grant_id, by="user")
    else:
        await broker.revoke(grant_id, "You stopped it", by="user")
    return {"ok": True}


@admin.get("/requests")
async def list_request_groups(user: User):
    """Pending requests, grouped so one answer covers everything an app asked for one task."""
    rows = await db.q(
        f"SELECT {GRANT_COLUMNS} FROM {GRANTS} WHERE a.user_id = ? AND g.status = 'pending'",
        user["id"],
    )
    return [{"id": grp[0]["id"], "title": grp[0]["task_title"], "grants": grp} for grp in groups.group(rows)]


class GroupDecision(BaseModel):
    grant_ids: list[str] = Field(min_length=1, max_length=50)


@admin.post("/requests/{action}")
async def decide_request_group(action: Literal["approve", "deny", "revoke"], body: GroupDecision, user: User):
    ids = list(dict.fromkeys(body.grant_ids))
    marks = ", ".join("?" * len(ids))
    owned = await db.one(
        f"SELECT COUNT(*) AS n FROM grants g JOIN agents a ON a.id = g.agent_id WHERE g.id IN ({marks}) AND a.user_id = ?",
        *ids,
        user["id"],
    )
    if not owned or owned["n"] != len(ids):
        raise AccessError("not_found", "Not found", 404)
    return {"done": await broker.decide_group(ids, action, by="user")}


# --- Activity ----------------------------------------------------------------

# Approvals and revocations carry only a grant id, so ownership goes through the grant.
EVENT_OWNER = f"COALESCE(e.agent_id, g.agent_id) IN ({OWNED_AGENTS})"


def _tz_offset_s() -> int:
    return int(datetime.now(ZoneInfo(settings().timezone)).utcoffset().total_seconds())  # type: ignore[union-attr]


@admin.get("/activity/daily")
async def activity_daily(user: User, days: int = 371):
    """Per-day counts for the heatmap, in the user's timezone."""
    since = db.now() - days * 86400
    rows = await db.q(
        f"""SELECT date(CAST(e.ts AS INTEGER) + ?, 'unixepoch') AS day,
            COUNT(*) AS total,
            SUM(CASE WHEN e.decision IN ('deny', 'revoke', 'redact') THEN 1 ELSE 0 END) AS blocked,
            SUM(CASE WHEN e.decision = 'ask' THEN 1 ELSE 0 END) AS asked
        FROM events e LEFT JOIN grants g ON g.id = e.grant_id
        WHERE e.ts > ? AND e.action != 'grant.revoke' AND {EVENT_OWNER}
        GROUP BY day ORDER BY day""",
        _tz_offset_s(),
        since,
        user["id"],
    )
    today = datetime.now(ZoneInfo(settings().timezone)).strftime("%Y-%m-%d")
    return {"today": today, "days": rows}


@admin.get("/events")
async def list_events(user: User, limit: int = 200, grant_id: str | None = None, blocked: bool = False, day: str | None = None):
    conds, params = [EVENT_OWNER], [user["id"]]
    if day:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=ZoneInfo(settings().timezone)).timestamp()
        conds.append("e.ts >= ? AND e.ts < ?")
        params += [start, start + 86400]
    if grant_id:
        conds.append("e.grant_id = ?")
        params.append(grant_id)
    if blocked:
        conds.append("e.decision IN ('deny', 'revoke', 'redact')")
    return await db.q(
        f"""SELECT e.*, COALESCE(a.name, ga.name) AS agent_name, COALESCE(a.kind, ga.kind) AS agent_kind,
            g.user_request, g.query_constraint, g.source, g.account, g.task_id, t.title AS task_title FROM events e
            LEFT JOIN agents a ON a.id = e.agent_id
            LEFT JOIN grants g ON g.id = e.grant_id
            LEFT JOIN tasks t ON t.id = g.task_id
            LEFT JOIN agents ga ON ga.id = g.agent_id
            WHERE {' AND '.join(conds)} ORDER BY e.ts DESC LIMIT ?""",
        *params,
        limit,
    )


@admin.get("/alerts")
async def list_alerts(user: User, limit: int = 100):
    return await db.q(
        f"""SELECT al.*, a.name AS agent_name, g.status AS grant_status FROM alerts al
            LEFT JOIN agents a ON a.id = al.agent_id
            LEFT JOIN grants g ON g.id = al.grant_id
            WHERE al.agent_id IN ({OWNED_AGENTS})
            ORDER BY al.ts DESC LIMIT ?""",
        user["id"],
        limit,
    )


@admin.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, user: User):
    await _owned(f"SELECT 1 AS ok FROM alerts WHERE id = ? AND agent_id IN ({OWNED_AGENTS})", alert_id, user["id"])
    await db.update("alerts", alert_id, status="resolved")
    return {"ok": True}


app.include_router(admin)


# ---------------------------------------------------------------------------
# Browser-facing: signed approve/deny links from push notifications


@app.api_route("/approvals/{grant_id}/{action}", methods=["GET", "POST"])
async def signed_approval(grant_id: str, action: Literal["approve", "deny"], sig: str, request: Request):
    if not verify(sig, grant_id, action):
        raise AccessError("bad_signature", "Link signature did not verify", 403)
    if request.method == "GET":
        # Link previews fetch URLs; only a POST acts.
        return HTMLResponse(
            f'<form method="post"><button style="font-size:2rem;padding:1rem 2rem">{action.title()}</button></form>'
        )
    if action == "approve":
        await broker.approve(grant_id, by="user (push)")
    else:
        await broker.deny(grant_id, by="user (push)")
    return {"ok": True, "action": action}


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privato</title><style>
body{{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,Inter,sans-serif;color:#1c1d1f;background:#fafafa}}
main{{max-width:420px;margin:0 auto;padding:40px 20px}}
.card{{background:#fff;border:1px solid #e6e6e9;border-radius:14px;padding:22px}}
h1{{font-size:19px;margin:0 0 6px}} p{{margin:0 0 6px;color:#5b5f66}} .q{{color:#1c1d1f}}
ul{{margin:14px 0;padding:10px 14px 10px 28px;background:#fff8eb;border-radius:10px;color:#7a4b06;font-size:14px}}
.row{{display:flex;gap:10px;margin-top:18px}} button{{flex:1;height:46px;border-radius:10px;font:600 15px inherit;cursor:pointer}}
.allow{{background:#1c1d1f;color:#fff;border:0}} .deny{{background:#fff;color:#1c1d1f;border:1px solid #e6e6e9}}
.brand{{display:flex;align-items:center;gap:8px;font-weight:600;margin-bottom:18px}} .meta{{font-size:14px}}
.items{{margin:14px 0;padding:0 0 0 20px;font-size:14px}} .items li{{padding:3px 0}}
</style></head><body><main><div class="brand">Privato</div><div class="card">{body}</div></main></body></html>"""
    )


@app.api_route("/approvals/{grant_id}", methods=["GET", "POST"])
async def review_request(grant_id: str, sig: str, request: Request):
    """The page a text message links to. GET only shows; link previews must not act."""
    if not verify(sig, grant_id, "review"):
        raise AccessError("bad_signature", "Link signature did not verify", 403)
    grant = await db.one("SELECT g.*, a.name AS agent_name, a.user_id FROM grants g JOIN agents a ON a.id = g.agent_id WHERE g.id = ?", grant_id)
    if not grant:
        raise AccessError("not_found", "Request not found", 404)
    name = escape(grant["agent_name"])
    batch = groups.group_of(grant_id, await broker.pending_requests(grant["user_id"])) if grant["status"] == "pending" else []
    for sid in {g["source"] for g in [grant, *batch] if g["source"].startswith("connector:")}:
        if row := await connectors.get(sid):
            connectors.as_source(row)
    if request.method == "POST":
        form = await request.form()
        action = form.get("action")
        # Only what the page showed, and only what still belongs with this request.
        shown = set(form.getlist("grant")) or {grant_id}
        picked = [g for g in batch if g["id"] in shown]
        if picked and action in ("approve", "deny"):
            await broker.decide_group([g["id"] for g in picked], action, by="user (text)")
            return _page(_outcome(name, action, picked))
    if grant["status"] != "pending":
        src = source(grant["source"])
        outcome = {
            "active": f"Allowed. {name} can see {escape(_what(grant))}.",
            "denied": f"Declined. {name} can't see your {src.items}.",
            "expired": "This access has already ended.",
            "revoked": "This access was stopped.",
        }.get(grant["status"], "Done.")
        return _page(f"<h1>{outcome}</h1><p>You can close this page.</p>")
    wants = _and([s.wants for s in dict.fromkeys(source(g["source"]) for g in batch)])
    questions = "".join(f'<p class="q">“{escape(q)}”</p>' for q in dict.fromkeys(g["user_request"] for g in batch))
    items = "".join(f"<li>{escape(_sentence(_what(g)))}</li>" for g in batch)
    ids = "".join(f'<input type="hidden" name="grant" value="{g["id"]}">' for g in batch)
    reasons = "".join(f"<li>{escape(r)}</li>" for r in dict.fromkeys(r for g in batch for r in (g["reason"] or "").split(". ") if r))
    allow = f"Allow all {len(batch)}" if len(batch) > 1 else "Allow"
    return _page(
        f"""<h1>{name} wants to {wants}</h1>
{questions}
<form method="post">{ids}<ol class="items">{items}</ol>
{f'<ul>{reasons}</ul>' if reasons else ''}
<div class="row"><button class="deny" name="action" value="deny">Don't allow</button>
<button class="allow" name="action" value="approve">{allow}</button></div></form>"""
    )


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def _what(grant: dict) -> str:
    src = source(grant["source"])
    duration = human_duration(grant["ttl_s"])
    if src.custom:
        return f"{_and(grant['scopes'] or ['its tools'])} in {src.label}, to {describe_filter(grant['query_constraint'], grant['source'])}, for {duration}"
    where = f" in {grant['account']}" if grant.get("account") else ""
    return f"{describe_filter(grant['query_constraint'], grant['source'])}{where} for {duration}"


def _outcome(name: str, action: str, decided: list[dict]) -> str:
    if action == "deny":
        items = _and([f"your {s.items}" for s in dict.fromkeys(source(g["source"]) for g in decided)])
        return f"<h1>Declined. {name} can't see {escape(items)}.</h1><p>You can close this page.</p>"
    lines = "".join(f"<li>{escape(_sentence(_what(g)))}</li>" for g in decided)
    return f'<h1>Allowed. {name} can see:</h1><ol class="items">{lines}</ol><p>You can close this page.</p>'


app.mount("/", _mcp_asgi)
