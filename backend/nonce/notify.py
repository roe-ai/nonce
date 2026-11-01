"""Alerts: stored for the dashboard, pushed to the user's phone (Web Push, ntfy) and texted when configured."""

import logging

import httpx

from . import db, sms, webpush
from .config import settings
from .crypto import sign

log = logging.getLogger(__name__)

PRIORITY = {"info": "default", "warning": "high", "critical": "urgent"}


def approval_link(grant_id: str, action: str) -> str:
    return f"{settings().public_url}/approvals/{grant_id}/{action}?sig={sign(grant_id, action)}"


def review_link(grant_id: str) -> str:
    """One link for texts: a page showing the request with Allow and Don't allow."""
    return f"{settings().public_url}/approvals/{grant_id}?sig={sign(grant_id, 'review')}"


async def alert(
    *,
    kind: str,
    severity: str,
    title: str,
    body: str,
    agent_id: str | None = None,
    grant_id: str | None = None,
    needs_approval: bool = False,
    quiet: bool = False,
) -> dict:
    """`quiet`: the user is in their offline hours, so a request waits on the dashboard without a text or push."""
    row = await db.insert(
        "alerts",
        {
            "ts": db.now(),
            "agent_id": agent_id,
            "grant_id": grant_id,
            "severity": severity,
            "kind": kind,
            "title": title,
            "body": body,
            "needs_approval": int(needs_approval),
            "status": "open",
        },
    )
    if quiet:
        return row
    if needs_approval or severity != "info":
        await _web_push(agent_id, title, body, row["id"], urgent=needs_approval or severity == "critical")
    await _push(title, body, severity, grant_id if needs_approval else None)
    if needs_approval or severity == "critical":
        await _text(agent_id, title, body, grant_id if needs_approval else None)
    return row


async def _web_push(agent_id: str | None, title: str, body: str, alert_id: str, *, urgent: bool) -> None:
    if not agent_id or not webpush.configured():
        return
    owner = await db.one("SELECT user_id FROM agents WHERE id = ?", agent_id)
    if not owner:
        return
    try:
        await webpush.send(owner["user_id"], title=title, body=body, url="/", tag=alert_id, urgent=urgent)
    except Exception:
        log.exception("web push failed")


async def _text(agent_id: str | None, title: str, body: str, approve_grant_id: str | None) -> None:
    if not agent_id or not sms.enabled():
        return
    user = await db.one(
        "SELECT u.phone FROM users u JOIN agents a ON a.user_id = u.id WHERE a.id = ? AND u.phone_verified_at IS NOT NULL",
        agent_id,
    )
    if not user or not user["phone"]:
        return
    tail = f"Allow or decline: {review_link(approve_grant_id)}" if approve_grant_id else settings().dashboard_url
    try:
        await sms.send_text(user["phone"], f"nonce: {title}\n{body}\n\n{tail}")
    except httpx.HTTPError:
        log.exception("text message failed")


async def _push(title: str, body: str, severity: str, approve_grant_id: str | None) -> None:
    s = settings()
    if not s.ntfy_topic:
        return
    payload: dict = {
        "topic": s.ntfy_topic,
        "title": title,
        "message": body,
        "priority": {"default": 3, "high": 4, "urgent": 5}[PRIORITY.get(severity, "default")],
        "tags": ["lock"],
        "click": s.dashboard_url,
    }
    if approve_grant_id:
        payload["actions"] = [
            {"action": "http", "label": "Approve", "url": approval_link(approve_grant_id, "approve"), "method": "POST", "clear": True},
            {"action": "http", "label": "Deny", "url": approval_link(approve_grant_id, "deny"), "method": "POST", "clear": True},
        ]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(s.ntfy_url, json=payload)
    except httpx.HTTPError:
        log.exception("ntfy push failed")
