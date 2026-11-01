"""Grants and data calls. REST and MCP are both thin layers over these functions.

A grant has a short TTL and a call budget, and can be revoked at any time. The user's
credentials never leave nonce: the agent holds an opaque grant token, and nonce runs
the Gmail, Calendar, Drive or Slack calls, or the tools on a connector the user added.
"""

import asyncio
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import accounts, connectors, db, groups, notify, oauth, recall, tasks
from .config import settings
from .crypto import hash_token, new_token
from .errors import AccessError
from .signals import Detector, load_detector
from .policy import AccessContext, decide_access, decide_search, is_injection, is_offline, mode
from .providers import Provider, check_filter, provider_for
from .providers.base import WITHHELD, withhold
from .sources import CONNECTOR_PREFIX, SOURCES, Source, source

_detector: Detector | None = None
_provider_overrides: dict[str, Provider] = {}

# How much of your history Cautious mode searches for look-alike questions.
HISTORY_LIMIT = 500
TASK_GRACE_S = 2.0


def detector() -> Detector:
    global _detector
    _detector = _detector or load_detector()
    return _detector


def use_detector(d: Detector | None) -> None:
    global _detector
    _detector = d


def use_provider(p: Provider | None, source_id: str = "gmail", account: str | None = None) -> None:
    key = f"{source_id}:{account}" if account else source_id
    if p is None:
        _provider_overrides.pop(key, None)
    else:
        _provider_overrides[key] = p


# ---------------------------------------------------------------------------
# Agents


async def create_agent(user_id: str, name: str, kind: str = "custom") -> tuple[dict, str]:
    key = new_token("nonce_agent")
    row = await db.insert(
        "agents",
        {
            "user_id": user_id,
            "name": name,
            "kind": kind,
            "key_hash": hash_token(key),
            "key_prefix": key[:16],
            "status": "active",
            "mode": "standard",
            "created_at": db.now(),
        },
    )
    return row, key


async def authenticate(key: str | None) -> dict:
    if not key:
        raise AccessError("unauthenticated", "Missing agent key (Authorization: Bearer nonce_agent_…)", 401)
    if key.startswith(("nonce_at_", "pvt_at_")):
        agent = await oauth.agent_for_access_token(key)
    else:
        agent = await db.one("SELECT * FROM agents WHERE key_hash = ?", hash_token(key))
    if not agent or agent["status"] != "active":
        raise AccessError("unauthenticated", "Unknown or disabled agent key", 401)
    await db.update("agents", agent["id"], last_seen_at=db.now())
    return agent


# ---------------------------------------------------------------------------
# Events


async def _event(
    action: str,
    decision: str,
    *,
    agent: dict | None = None,
    grant_id: str | None = None,
    reason: str = "",
    detail: dict | None = None,
    signals: dict | None = None,
    started: float | None = None,
) -> None:
    await db.insert(
        "events",
        {
            "ts": db.now(),
            "agent_id": agent["id"] if agent else None,
            "grant_id": grant_id,
            "action": action,
            "decision": decision,
            "reason": reason,
            "detail": detail or {},
            "signals": signals,
            "latency_ms": int((time.perf_counter() - started) * 1000) if started else None,
        },
    )


# ---------------------------------------------------------------------------
# Access requests


async def list_sources(agent: dict) -> dict:
    """What this app can ask for: each connected kind of data with its accounts, and the user's connectors."""
    return {
        "sources": await accounts.for_agents(agent["user_id"]),
        "connectors": await connectors.for_agents(agent["user_id"]),
    }


async def _target(
    agent: dict, source_id: str, wanted: list[str] | None, query: str, scopes: list[str] | None
) -> tuple[Source, str, str, bool, list[str], list[str] | None]:
    """The source a request is for, the connection or connector behind it, its account label, whether the user has
    several accounts of this kind, scopes, and the accounts it names (None: every active one)."""
    if source_id.startswith(CONNECTOR_PREFIX):
        row = await connectors.get(source_id)
        if not row or row["user_id"] != agent["user_id"]:
            raise AccessError("bad_request", f"Unknown source '{source_id}'. Call list_sources to see what you can ask for.", 400)
        if row["status"] != "active":
            raise AccessError("connector_paused", f"The user paused {row['name']} in nonce", 409)
        src = connectors.as_source(row)
        auto = sorted(src.tools - src.ask_tools)
        return src, row["id"], row["name"], False, scopes or auto or sorted(src.tools), None
    if source_id not in SOURCES:
        raise AccessError("bad_request", f"Unknown source '{source_id}'. Use one of: {', '.join(SOURCES)}, or a connector from list_sources", 400)
    src = SOURCES[source_id]
    check_filter(src.id, query)
    chosen, rows = await accounts.pick(agent["user_id"], src, wanted)
    ids = [r["id"] for r in chosen] if wanted else None
    return src, chosen[0]["id"], accounts.label(chosen), len(rows) > 1, scopes or [src.metadata_scope], ids


def local_hour(user: dict | None) -> int:
    tz = (user or {}).get("timezone") or settings().timezone
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(settings().timezone)
    return datetime.now(zone).hour


def offline_hours(user: dict | None) -> tuple[int, int]:
    """The user's own offline hours, or the server default (QUIET_HOURS)."""
    u = user or {}
    if u.get("offline_start") is not None and u.get("offline_end") is not None:
        return u["offline_start"], u["offline_end"]
    return settings().quiet_hours


async def _past_questions(user_id: str) -> list[dict]:
    """Requests you allowed (or nonce allowed for you), newest first."""
    rows = await db.q(
        """SELECT g.id, g.user_request, g.source, g.created_at FROM grants g JOIN agents a ON a.id = g.agent_id
        WHERE a.user_id = ? AND g.activated_at IS NOT NULL ORDER BY g.created_at DESC LIMIT ?""",
        user_id,
        HISTORY_LIMIT,
    )
    return [
        {
            "id": r["id"][:8],
            "question": r["user_request"],
            "source": source(r["source"]).label,
            "date": datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d"),
        }
        for r in rows
    ]


async def _access_context(agent: dict, user: dict | None, history: list[dict]) -> AccessContext:
    since = db.now() - 3600
    recent = await db.one("SELECT COUNT(*) AS n FROM grants WHERE agent_id = ? AND created_at > ?", agent["id"], since)
    cats = await db.q(
        "SELECT DISTINCT category FROM grants WHERE agent_id = ? AND activated_at IS NOT NULL AND category IS NOT NULL",
        agent["id"],
    )
    start, end = offline_hours(user)
    return AccessContext(
        requests_last_hour=recent["n"] if recent else 0,
        known_categories={c["category"] for c in cats},
        offline=is_offline(local_hour(user), start, end),
        history_size=len(history),
    )


def _grant_view(grant: dict, token: str | None = None) -> dict:
    now = db.now()
    src = source(grant.get("source"))
    view = {
        "grant_id": grant["id"],
        "source": src.id,
        "account": grant.get("account"),
        "status": grant["status"],
        "scopes": grant["scopes"],
        "query_constraint": grant["query_constraint"],
        "expires_in_s": max(0, int(grant["expires_at"] - now)) if grant.get("expires_at") else None,
        "calls_left": grant["max_calls"] - grant["calls_used"],
        "reason": grant.get("reason"),
    }
    if token:
        view["grant_token"] = token
    view["next_step"] = {
        "active": f"Call connector_call with this grant_token and one of these tools: {', '.join(grant['scopes'])}."
        if src.custom
        else f"Call {src.id}_search with this grant_token. Searches are limited to query_constraint.",
        "pending": "Waiting for the user to approve in nonce. Tell them in one line, then end your turn with a "
        '"Check approval and continue" button or quick reply (or ask them to reply "continue"). '
        "When they continue, call check_access with this grant_token and resume their original question.",
        "denied": "Do not retry with a broader request. Tell the user nonce denied access and why.",
        "revoked": "Access ended. Ask the user before requesting access again.",
        "expired": "Access expired. Request access again if the user still needs it.",
    }[grant["status"]]
    return view


async def request_access(
    agent: dict,
    *,
    user_request: str,
    justification: str,
    query: str,
    scopes: list[str] | None = None,
    duration_minutes: int | None = None,
    source: str = "gmail",
    account: str | list[str] | None = None,
) -> dict:
    started = time.perf_counter()
    s = settings()
    wanted = [account] if isinstance(account, str) else account
    src, connection_id, account_label, many, scopes, account_ids = await _target(agent, source, wanted, query, scopes)
    ttl_s = int(duration_minutes * 60) if duration_minutes else s.default_ttl_s
    app_mode = mode(agent.get("mode"))
    user = await db.one("SELECT * FROM users WHERE id = ?", agent["user_id"])

    state: dict[str, Any] = {
        "agent": agent["name"],
        "data_source": src.label,
        "account": account_label,
        "user_request": user_request,
        "justification": justification,
        "filter": query,
        "scopes": scopes,
        "requested_duration_minutes": ttl_s // 60,
    }
    task_id, new_task = await tasks.claim(agent["id"], user_request, src.label)
    refining = asyncio.create_task(tasks.refine(task_id, agent["id"], user_request, src.label)) if new_task else None
    history = await _past_questions(agent["user_id"]) if app_mode.must_be_familiar else []
    found = await recall.recall(user_request, src.label, history) if history else None
    if found and found.compare:
        state["previous_requests"] = found.compare
    signals = await detector().access(state)
    if signals is not None and found:
        signals = {**signals, "recall_by": found.by, "recall_queries": found.queries}
        if found.closest:
            signals.update(closest=found.closest[0], closest_score=round(found.closest[1], 3))
    ctx = await _access_context(agent, user, history)
    decision = decide_access(src=src, mode=app_mode, scopes=scopes, constraint=query, ttl_s=ttl_s, signals=signals, ctx=ctx)

    status = {"allow": "active", "ask": "pending", "deny": "denied"}[decision.outcome]
    if refining:
        # Luna usually finishes alongside the signals read; past a short grace the task keeps its claimed place.
        await asyncio.wait([refining], timeout=TASK_GRACE_S)
    task_id = await tasks.resolve(task_id)
    token = new_token("nonce_grant")
    now = db.now()
    grant = await db.insert(
        "grants",
        {
            "agent_id": agent["id"],
            "connection_id": connection_id,
            "source": src.id,
            "account": account_label,
            "account_ids": account_ids,
            "task_id": task_id,
            "token_hash": hash_token(token),
            "status": status,
            "scopes": scopes,
            "query_constraint": query,
            "justification": justification,
            "user_request": user_request,
            "category": (signals or {}).get("category"),
            "ttl_s": ttl_s,
            "max_calls": s.default_max_calls,
            "calls_used": 0,
            "decided_by": "policy" if status != "pending" else None,
            "reason": decision.reason,
            "signals": signals,
            "created_at": now,
            "activated_at": now if status == "active" else None,
            "expires_at": now + ttl_s if status == "active" else None,
            "ended_at": now if status == "denied" else None,
        },
    )
    await _event(
        "access.request",
        decision.outcome,
        agent=agent,
        grant_id=grant["id"],
        reason=decision.reason,
        detail={
            "source": src.id,
            "account": account_label,
            "user_request": user_request,
            "justification": justification,
            "query": query,
            "scopes": scopes,
            "ttl_s": ttl_s,
            "mode": app_mode.name,
        },
        signals=signals,
        started=started,
    )

    if status == "pending":
        # A group of waiting requests shares one approval page, so only its earliest request notifies. Requests made
        # at the same moment can all see each other, so "earliest" has to be decided the same way by each of them.
        first = (grant["created_at"], grant["id"])
        joined = any((g["created_at"], g["id"]) < first for g in groups.group_of(grant["id"], await pending_requests(agent["user_id"])))
        await notify.alert(
            kind="approval",
            severity="warning",
            title=f"{agent['name']} wants to {src.wants}" + (f" ({account_label})" if many else ""),
            body=f"For: “{user_request}”\n{'. '.join(decision.reasons)}.",
            agent_id=agent["id"],
            grant_id=grant["id"],
            needs_approval=True,
            quiet=ctx.offline or joined,
        )
    elif status == "denied":
        await notify.alert(
            kind="denied",
            severity="warning",
            title=f"Blocked {agent['name']}",
            body=f"{'. '.join(decision.reasons)}.",
            agent_id=agent["id"],
            grant_id=grant["id"],
        )
    return _grant_view(grant, token)


async def check_access(agent: dict, grant_token: str) -> dict:
    grant = await _grant_for(agent, grant_token, require_active=False)
    return _grant_view(grant)


# ---------------------------------------------------------------------------
# Grant lifecycle


async def _expire_if_due(grant: dict) -> dict:
    if grant["status"] == "active" and grant["expires_at"] and grant["expires_at"] <= db.now():
        await db.update("grants", grant["id"], status="expired", ended_at=grant["expires_at"])
        grant = {**grant, "status": "expired"}
    return grant


async def _grant_for(agent: dict, grant_token: str, *, require_active: bool = True, source_id: str | None = None) -> dict:
    grant = await db.one("SELECT * FROM grants WHERE token_hash = ?", hash_token(grant_token or ""))
    if not grant:
        raise AccessError("invalid_grant", "Unknown grant token. Call request_access first.")
    if grant["agent_id"] != agent["id"]:
        owner = await db.one("SELECT name FROM agents WHERE id = ?", grant["agent_id"])
        await revoke(grant["id"], f"{agent['name']} tried to use it")
        await _event("grant.misuse", "deny", agent=agent, grant_id=grant["id"], reason=f"It used access you gave to {owner['name'] if owner else 'another app'}")
        await notify.alert(
            kind="token_misuse",
            severity="critical",
            title=f"Blocked {agent['name']}",
            body=f"It tried to use access you gave to {owner['name'] if owner else 'another app'}. That access is now closed.",
            agent_id=agent["id"],
            grant_id=grant["id"],
        )
        raise AccessError("token_mismatch", "This grant was issued to a different agent. It has been revoked.")
    if source_id and grant["source"] != source_id:
        held = source(grant["source"])
        use = "connector_call" if held.custom else f"{held.id}_search and {held.id}_read"
        raise AccessError("wrong_source", f"This grant is for {held.label}. Use {use} with it.")
    grant = await _expire_if_due(grant)
    if require_active and grant["status"] != "active":
        raise AccessError(f"grant_{grant['status']}", _grant_view(grant)["next_step"])
    return grant


async def pending_requests(user_id: str) -> list[dict]:
    return await db.q(
        """SELECT g.*, a.name AS agent_name, a.kind AS agent_kind FROM grants g JOIN agents a ON a.id = g.agent_id
        WHERE a.user_id = ? AND g.status = 'pending' ORDER BY g.created_at""",
        user_id,
    )


async def decide_group(grant_ids: list[str], action: str, by: str = "user") -> list[str]:
    """Approve, deny or stop each request the user saw. Ones decided in the meantime are skipped."""
    done = []
    for grant_id in dict.fromkeys(grant_ids):
        try:
            if action == "revoke":
                await revoke(grant_id, "You stopped it", by=by)
            else:
                await (approve if action == "approve" else deny)(grant_id, by=by)
            done.append(grant_id)
        except AccessError as e:
            if e.code != "not_pending":
                raise
    return done


async def approve(grant_id: str, by: str = "user") -> dict:
    grant = await db.one("SELECT * FROM grants WHERE id = ?", grant_id)
    if not grant or grant["status"] != "pending":
        raise AccessError("not_pending", "Only pending requests can be approved", 409)
    now = db.now()
    await db.update("grants", grant_id, status="active", decided_by=by, activated_at=now, expires_at=now + grant["ttl_s"])
    await db.q("UPDATE alerts SET status = 'resolved' WHERE grant_id = ? AND needs_approval = 1", grant_id)
    await _event("access.approve", "allow", grant_id=grant_id, reason=f"approved by {by}", detail={"agent_id": grant["agent_id"]})
    return await db.one("SELECT * FROM grants WHERE id = ?", grant_id)  # type: ignore[return-value]


async def deny(grant_id: str, by: str = "user") -> None:
    grant = await db.one("SELECT * FROM grants WHERE id = ?", grant_id)
    if not grant or grant["status"] != "pending":
        raise AccessError("not_pending", "Only pending requests can be denied", 409)
    await db.update("grants", grant_id, status="denied", decided_by=by, ended_at=db.now(), reason=f"denied by {by}")
    await db.q("UPDATE alerts SET status = 'resolved' WHERE grant_id = ? AND needs_approval = 1", grant_id)
    await _event("access.deny", "deny", grant_id=grant_id, reason=f"denied by {by}")


async def revoke(grant_id: str, reason: str, by: str = "nonce") -> None:
    grant = await db.one("SELECT * FROM grants WHERE id = ?", grant_id)
    if not grant or grant["status"] not in ("active", "pending"):
        return
    await db.update("grants", grant_id, status="revoked", ended_at=db.now(), reason=f"revoked by {by}: {reason}")
    await db.q("UPDATE alerts SET status = 'resolved' WHERE grant_id = ? AND needs_approval = 1", grant_id)
    await _event("grant.revoke", "revoke", grant_id=grant_id, reason=reason, detail={"by": by, "agent_id": grant["agent_id"]})


async def _use_call(grant: dict) -> None:
    used = grant["calls_used"] + 1
    fields: dict[str, Any] = {"calls_used": used}
    if used >= grant["max_calls"]:
        fields.update(status="expired", ended_at=db.now())
    await db.update("grants", grant["id"], **fields)


# Item ids handed to apps name their account, so a read goes to the inbox the search found it in.
ITEM_SEP = "~"


async def _accounts_for(user_id: str, grant: dict) -> list[dict]:
    """The active accounts a grant reads right now: the ones it names, or every active one of its kind."""
    rows = await accounts.active(user_id, grant["source"])
    if grant.get("account_ids") is not None:
        rows = [r for r in rows if r["id"] in grant["account_ids"]]
    if not rows:
        raise AccessError("no_connection", f"The user paused or removed the {source(grant['source']).label} account behind this grant", 409)
    return rows


def _provider_for(conn: dict) -> Provider:
    return _provider_overrides.get(f"{conn['provider']}:{conn['account']}") or _provider_overrides.get(conn["provider"]) or provider_for(conn)


def _interleave(batches: list[list[Any]], limit: int) -> list[Any]:
    out: list[Any] = []
    for i in range(max((len(b) for b in batches), default=0)):
        out.extend(b[i] for b in batches if i < len(b))
    return out[:limit]


async def choose_accounts(user_id: str, grant_id: str, connection_ids: list[str]) -> dict:
    """You change which accounts a waiting request reads before you approve it."""
    grant = await db.one("SELECT g.* FROM grants g JOIN agents a ON a.id = g.agent_id WHERE g.id = ? AND a.user_id = ?", grant_id, user_id)
    if not grant:
        raise AccessError("not_found", "Not found", 404)
    if grant["status"] != "pending":
        raise AccessError("not_pending", "Only a request that's waiting for you can change accounts", 409)
    rows = [r for r in await accounts.active(user_id, grant["source"]) if r["id"] in set(connection_ids)]
    if not rows:
        raise AccessError("bad_request", "Pick at least one account", 400)
    await db.update("grants", grant_id, account_ids=[r["id"] for r in rows], account=accounts.label(rows), connection_id=rows[0]["id"])
    return {"ok": True}


async def end_grants_without_accounts(user_id: str, provider: str, reason: str) -> None:
    """After you pause or remove an account: access that has no account left ends; the rest just stops reading it."""
    grants = await db.q(
        "SELECT g.* FROM grants g JOIN agents a ON a.id = g.agent_id WHERE a.user_id = ? AND g.source = ? AND g.status IN ('active', 'pending')",
        user_id,
        provider,
    )
    for g in grants:
        try:
            await _accounts_for(user_id, g)
        except AccessError:
            await revoke(g["id"], reason, by="user")


async def _revoke_and_alert(agent: dict, grant: dict, reason: str, title: str) -> None:
    await revoke(grant["id"], reason)
    await notify.alert(
        kind="revoked",
        severity="critical",
        title=title,
        body=f"You asked: “{grant['user_request']}”. {reason}.",
        agent_id=agent["id"],
        grant_id=grant["id"],
    )


# ---------------------------------------------------------------------------
# Data calls: search inside the grant's filter, then read what the search returned


async def search(agent: dict, source_id: str, grant_token: str, query: str = "", max_results: int = 10) -> dict:
    started = time.perf_counter()
    grant = await _grant_for(agent, grant_token, source_id=source_id)
    src = source(grant["source"])
    check_filter(src.id, query)
    limit = max(1, min(max_results, settings().max_results_per_search))
    action = f"{src.id}.search"

    recent = await db.one(
        "SELECT COUNT(*) AS n FROM events WHERE grant_id = ? AND action = ? AND ts > ? AND decision IN ('allow', 'warn')",
        grant["id"],
        action,
        db.now() - 60,
    )
    if query.strip():
        signals = await detector().search(
            {
                "data_source": src.label,
                "user_request": grant["user_request"],
                "justification": grant["justification"],
                "granted_filter": grant["query_constraint"],
                "search_query": query,
            }
        )
    else:
        signals = {"serves": 1.0, "crawl": 0.0, "category": grant["category"], "note": "no extra query; grant filter only"}
    decision = decide_search(src=src, mode=mode(agent.get("mode")), grant=grant, searches_last_minute=recent["n"] if recent else 0, signals=signals)
    detail: dict[str, Any] = {"query": query, "effective_query": f"({grant['query_constraint']}) ({query})" if query else grant["query_constraint"]}

    if decision.outcome == "revoke":
        await _event(action, "revoke", agent=agent, grant_id=grant["id"], reason=decision.reason, detail=detail, signals=signals, started=started)
        await _revoke_and_alert(agent, grant, decision.reason, f"Stopped {agent['name']}")
        raise AccessError("grant_revoked", f"nonce revoked this grant: {decision.reason}. Tell the user.")

    conns = await _accounts_for(agent["user_id"], grant)
    batches = await asyncio.gather(*(_provider_for(c).search(grant["query_constraint"], query, limit) for c in conns))
    results = _interleave([[(c, item) for item in batch] for c, batch in zip(conns, batches, strict=True)], limit)
    if results:
        await db.q(
            f"INSERT OR IGNORE INTO grant_messages (grant_id, message_id) VALUES {', '.join(['(?, ?)'] * len(results))}",
            *[v for c, item in results for v in (grant["id"], _item_id(c, item.id, len(conns) > 1))],
        )
    await _use_call(grant)
    detail["result_count"] = len(results)
    await _event(action, decision.outcome, agent=agent, grant_id=grant["id"], reason=decision.reason, detail=detail, signals=signals, started=started)
    if decision.outcome == "warn":
        await notify.alert(
            kind="drift",
            severity="info",
            title=f"{agent['name']} searched a bit off-topic",
            body=f"You asked: “{grant['user_request']}”. It searched for “{query}”.",
            agent_id=agent["id"],
            grant_id=grant["id"],
        )
    key = {"gmail": "messages", "calendar": "events", "drive": "files", "slack": "messages"}[src.id]
    return {
        key: [_tagged(item.view(grant["scopes"]), c, len(conns) > 1) for c, item in results],
        "grant": {"expires_in_s": max(0, int(grant["expires_at"] - db.now())), "calls_left": grant["max_calls"] - grant["calls_used"] - 1},
    }


async def read(agent: dict, source_id: str, grant_token: str, item_id: str) -> dict:
    started = time.perf_counter()
    grant = await _grant_for(agent, grant_token, source_id=source_id)
    src = source(grant["source"])
    action = f"{src.id}.read"
    seen = await db.one("SELECT 1 AS ok FROM grant_messages WHERE grant_id = ? AND message_id = ?", grant["id"], item_id)
    if not seen:
        reason = f"It tried to open {src.items} it wasn't given"
        await _event(action, "revoke", agent=agent, grant_id=grant["id"], reason=reason, detail={"item_id": item_id}, started=started)
        await _revoke_and_alert(agent, grant, reason, f"Stopped {agent['name']}")
        raise AccessError("grant_revoked", f"nonce revoked this grant: {reason}.")

    with_content = src.content_scope in grant["scopes"]
    conn_id, tagged, raw_id = item_id.partition(ITEM_SEP)
    if not tagged:
        conn_id, raw_id = grant["connection_id"], item_id
    conns = await _accounts_for(agent["user_id"], grant)
    conn = next((c for c in conns if c["id"] == conn_id), None)
    if not conn:
        raise AccessError("no_connection", f"The user paused or removed the {src.label} account this {src.item} is in", 409)
    item = await _provider_for(conn).get(raw_id, content=with_content)
    if not item:
        raise AccessError("not_found", f"That {src.item} wasn't found", 404)
    view = _tagged(item.view(grant["scopes"], full=True), conn, len(conns) > 1)
    signals = None
    decision, reason = "allow", "Within the access you gave"
    if with_content:
        signals = await detector().content({"data_source": src.label, **item.for_check()})
        if is_injection(signals):
            decision, reason = "redact", f"This {src.item} tries to give the AI instructions"
            view = withhold(view, item.CONTENT_FIELDS)
            await db.update("grants", grant["id"], signals={**(grant["signals"] or {}), "injection_seen": True})
            await notify.alert(
                kind="injection",
                severity="warning",
                title=f"Caught a suspicious {src.item}",
                body=f"“{item.title}” tried to give {agent['name']} instructions. We hid it from {agent['name']} and are watching more closely.",
                agent_id=agent["id"],
                grant_id=grant["id"],
            )
    await _use_call(grant)
    await _event(action, decision, agent=agent, grant_id=grant["id"], reason=reason, detail={"item_id": item_id, "title": item.title}, signals=signals, started=started)
    return {{"gmail": "message", "calendar": "event", "drive": "file", "slack": "message"}[src.id]: view}


def _item_id(conn: dict, item_id: str, several: bool) -> str:
    return f"{conn['id']}{ITEM_SEP}{item_id}" if several else item_id


def _tagged(view: dict[str, Any], conn: dict, several: bool) -> dict[str, Any]:
    """With several accounts, an item's id names its account and the app sees which one it's from."""
    if several:
        view["id"] = _item_id(conn, view["id"], several)
        view["account"] = conn["account"]
    return view


async def gmail_search(agent: dict, grant_token: str, query: str = "", max_results: int = 10) -> dict:
    return await search(agent, "gmail", grant_token, query, max_results)


async def gmail_read(agent: dict, grant_token: str, message_id: str) -> dict:
    return await read(agent, "gmail", grant_token, message_id)


# ---------------------------------------------------------------------------
# Connector calls: one tool on a server the user added, inside a grant that lists it


async def connector_call(agent: dict, grant_token: str, tool: str, arguments: dict | None = None) -> dict:
    started = time.perf_counter()
    arguments = arguments or {}
    grant = await _grant_for(agent, grant_token)
    if not grant["source"].startswith(CONNECTOR_PREFIX):
        held = source(grant["source"])
        raise AccessError("wrong_source", f"This grant is for {held.label}. Use {held.id}_search and {held.id}_read with it.")
    row = await connectors.get(grant["source"])
    if not row or row["status"] != "active":
        raise AccessError("no_connection", "The user removed or paused the connector behind this grant", 409)
    src = connectors.as_source(row)
    if tool not in grant["scopes"]:
        raise AccessError("tool_not_granted", f"This grant covers {', '.join(grant['scopes'])}. Request access again to use {tool}.")
    if tool not in src.tools:
        raise AccessError("tool_off", f"The user turned off {tool} in {src.label}.")

    action = "connector.call"
    shown = connectors.args_shown(arguments)
    detail: dict[str, Any] = {"source": src.id, "connector": src.label, "tool": tool, "arguments": shown}
    recent = await db.one(
        "SELECT COUNT(*) AS n FROM events WHERE grant_id = ? AND action = ? AND ts > ? AND decision IN ('allow', 'warn')",
        grant["id"],
        action,
        db.now() - 60,
    )
    signals = await detector().search(
        {
            "data_source": src.label,
            "user_request": grant["user_request"],
            "justification": grant["justification"],
            "granted_filter": grant["query_constraint"],
            "search_query": f"{tool} {shown}",
        }
    )
    decision = decide_search(src=src, mode=mode(agent.get("mode")), grant=grant, searches_last_minute=recent["n"] if recent else 0, signals=signals)
    if decision.outcome == "revoke":
        await _event(action, "revoke", agent=agent, grant_id=grant["id"], reason=decision.reason, detail=detail, signals=signals, started=started)
        await _revoke_and_alert(agent, grant, decision.reason, f"Stopped {agent['name']}")
        raise AccessError("grant_revoked", f"nonce revoked this grant: {decision.reason}. Tell the user.")

    text, is_error = await connectors.call(row, tool, arguments)
    outcome, reason = decision.outcome, decision.reason
    content_signals = await detector().content({"data_source": src.label, "title": f"Result of {tool}", "text": text[:8000]}) if text else None
    if is_injection(content_signals):
        text, outcome, reason = WITHHELD, "redact", f"What {tool} returned tries to give the AI instructions"
        await db.update("grants", grant["id"], signals={**(grant["signals"] or {}), "injection_seen": True})
        await notify.alert(
            kind="injection",
            severity="warning",
            title=f"Caught a suspicious result from {src.label}",
            body=f"{tool} returned text that tried to give {agent['name']} instructions. We hid it and are watching more closely.",
            agent_id=agent["id"],
            grant_id=grant["id"],
        )
    await _use_call(grant)
    detail["is_error"] = is_error
    await _event(action, outcome, agent=agent, grant_id=grant["id"], reason=reason, detail=detail, signals=signals, started=started)
    if decision.outcome == "warn":
        await notify.alert(
            kind="drift",
            severity="info",
            title=f"{agent['name']} used {src.label} a bit off-topic",
            body=f"You asked: “{grant['user_request']}”. It called {tool}.",
            agent_id=agent["id"],
            grant_id=grant["id"],
        )
    return {
        "result": text,
        "is_error": is_error,
        "grant": {"expires_in_s": max(0, int(grant["expires_at"] - db.now())), "calls_left": grant["max_calls"] - grant["calls_used"] - 1},
    }
