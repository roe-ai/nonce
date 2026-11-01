"""Connected accounts. A user can connect several of each (two Gmail inboxes, two Slack workspaces).

Each account is on or paused. An app reads every active account of a kind unless it names some;
you can change which ones before approving.
"""

from . import db
from .errors import AccessError
from .sources import SOURCES, Source


async def save(user_id: str, provider: str, mode: str, account: str, credentials_enc: str) -> dict:
    """Adds an account, or replaces it (keeping its place) if the same one was connected before."""
    before = await db.one(
        "SELECT created_at FROM connections WHERE user_id = ? AND provider = ? AND lower(account) = lower(?) AND status IN ('active', 'paused')",
        user_id,
        provider,
        account,
    )
    await db.q(
        "UPDATE connections SET status = 'replaced', credentials_enc = NULL WHERE user_id = ? AND provider = ? AND lower(account) = lower(?) AND status IN ('active', 'paused')",
        user_id,
        provider,
        account,
    )
    return await db.insert(
        "connections",
        {"user_id": user_id, "provider": provider, "mode": mode, "account": account, "credentials_enc": credentials_enc, "status": "active", "created_at": before["created_at"] if before else db.now()},
    )


async def of(user_id: str, provider: str | None = None) -> list[dict]:
    """The user's accounts (on or paused), oldest first."""
    where = "AND provider = ?" if provider else ""
    return await db.q(
        f"""SELECT id, provider, mode, account, status, created_at FROM connections
        WHERE user_id = ? AND status IN ('active', 'paused') AND provider != 'connector' {where} ORDER BY created_at""",
        user_id,
        *([provider] if provider else []),
    )


async def active(user_id: str, provider: str) -> list[dict]:
    """Active accounts with their credentials, oldest first."""
    return await db.q(
        "SELECT * FROM connections WHERE user_id = ? AND provider = ? AND status = 'active' ORDER BY created_at",
        user_id,
        provider,
    )


def label(rows: list[dict]) -> str:
    return ", ".join(r["account"] or "" for r in rows)


async def pick(user_id: str, src: Source, wanted: list[str] | None) -> tuple[list[dict], list[dict]]:
    """The accounts a request names (every active one when it names none), and all active accounts of this kind."""
    rows = await active(user_id, src.id)
    if not rows:
        if await of(user_id, src.id):
            raise AccessError("account_paused", f"The user paused {src.label} in nonce", 409)
        raise AccessError("no_connection", f"The user has not connected {src.label} to nonce", 409)
    if not wanted:
        return rows, rows
    by_name = {(r["account"] or "").lower(): r for r in rows}
    unknown = [w for w in wanted if w.strip().lower() not in by_name]
    if unknown:
        names = ", ".join(r["account"] for r in rows)
        raise AccessError("unknown_account", f"No {src.label} account '{unknown[0]}'. Connected: {names}", 400)
    chosen = {by_name[w.strip().lower()]["id"] for w in wanted}
    return [r for r in rows if r["id"] in chosen], rows


async def owned(user_id: str, connection_id: str) -> dict:
    row = await db.one("SELECT * FROM connections WHERE id = ? AND user_id = ? AND status IN ('active', 'paused') AND provider != 'connector'", connection_id, user_id)
    if not row:
        raise AccessError("not_found", "Not found", 404)
    return row


async def set_paused(user_id: str, connection_id: str, paused: bool) -> dict:
    row = await owned(user_id, connection_id)
    await db.update("connections", connection_id, status="paused" if paused else "active")
    return row


async def remove(user_id: str, connection_id: str) -> dict:
    row = await owned(user_id, connection_id)
    await db.update("connections", connection_id, status="removed", credentials_enc=None)
    return row


async def for_agents(user_id: str) -> list[dict]:
    """What an app can ask for: each kind of data with its accounts."""
    out: list[dict] = []
    for r in await of(user_id):
        if r["status"] != "active" or r["provider"] not in SOURCES:
            continue
        entry = next((e for e in out if e["source"] == r["provider"]), None)
        if not entry:
            src = SOURCES[r["provider"]]
            entry = {"source": src.id, "label": src.label, "filter": src.syntax, "accounts": []}
            out.append(entry)
        entry["accounts"].append(r["account"])
    return out
