"""libSQL access. Turso when TURSO_DATABASE_URL is set, otherwise a local SQLite file.

The libsql driver is synchronous, so calls run on a worker thread behind one lock.
"""

import asyncio
import json
import threading
import time
import uuid
from typing import Any

import libsql

from .config import settings

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        google_sub TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL,
        name TEXT,
        picture TEXT,
        created_at REAL NOT NULL,
        last_login_at REAL
    )""",
    """CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'custom',
        key_hash TEXT NOT NULL UNIQUE,
        key_prefix TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at REAL NOT NULL,
        last_seen_at REAL
    )""",
    """CREATE TABLE IF NOT EXISTS connections (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        mode TEXT NOT NULL,
        account TEXT,
        credentials_enc TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS grants (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL REFERENCES agents(id),
        connection_id TEXT NOT NULL REFERENCES connections(id),
        token_hash TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        scopes TEXT NOT NULL,
        query_constraint TEXT NOT NULL,
        justification TEXT NOT NULL,
        user_request TEXT NOT NULL,
        category TEXT,
        ttl_s INTEGER NOT NULL,
        max_calls INTEGER NOT NULL,
        calls_used INTEGER NOT NULL DEFAULT 0,
        decided_by TEXT,
        reason TEXT,
        signals TEXT,
        created_at REAL NOT NULL,
        activated_at REAL,
        expires_at REAL,
        ended_at REAL
    )""",
    "CREATE INDEX IF NOT EXISTS grants_agent ON grants(agent_id, created_at)",
    """CREATE TABLE IF NOT EXISTS grant_messages (
        grant_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        PRIMARY KEY (grant_id, message_id)
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        ts REAL NOT NULL,
        agent_id TEXT,
        grant_id TEXT,
        action TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT,
        detail TEXT,
        signals TEXT,
        latency_ms INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS events_ts ON events(ts)",
    "CREATE INDEX IF NOT EXISTS events_grant ON events(grant_id, ts)",
    """CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        ts REAL NOT NULL,
        agent_id TEXT,
        grant_id TEXT,
        severity TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        needs_approval INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open'
    )""",
    "CREATE INDEX IF NOT EXISTS alerts_ts ON alerts(ts)",
    # OAuth for the MCP endpoint: registered clients (ChatGPT, Claude…), consent requests
    # waiting on the dashboard, one-time codes, and access/refresh tokens. Secrets are hashed.
    """CREATE TABLE IF NOT EXISTS oauth_clients (
        client_id TEXT PRIMARY KEY,
        info TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_requests (
        id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        params TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_codes (
        code_hash TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        params TEXT NOT NULL,
        expires_at REAL NOT NULL,
        used INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_tokens (
        token_hash TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        client_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        family TEXT NOT NULL,
        scopes TEXT NOT NULL,
        resource TEXT,
        expires_at REAL NOT NULL,
        revoked_at REAL,
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS oauth_tokens_agent ON oauth_tokens(agent_id)",
    "CREATE INDEX IF NOT EXISTS oauth_tokens_family ON oauth_tokens(family)",
    # What an app was doing when it asked: requests for one task are approved, shown and stopped together.
    """CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL REFERENCES agents(id),
        title TEXT NOT NULL,
        questions TEXT,
        placed_by TEXT NOT NULL,
        merged_into TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS tasks_agent ON tasks(agent_id, updated_at)",
    # Browsers (usually the dashboard installed on a phone) that get Web Push alerts.
    """CREATE TABLE IF NOT EXISTS push_subscriptions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        device TEXT,
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS push_subscriptions_user ON push_subscriptions(user_id)",
    # The user's own MCP servers and HTTP APIs. auth_enc is the Fernet-encrypted header; tools carry each tool's rule.
    # Each has a connections row with the same id (provider 'connector') for its grants to point at.
    """CREATE TABLE IF NOT EXISTS connectors (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        url TEXT NOT NULL,
        auth_header TEXT,
        auth_enc TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        tools TEXT,
        error TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS connectors_user ON connectors(user_id, status)",
]

# Columns added after the first release; ALTER TABLE has no IF NOT EXISTS in SQLite.
ADDED_COLUMNS = [
    ("agents", "user_id", "TEXT"),
    ("connections", "user_id", "TEXT"),
    ("users", "phone", "TEXT"),
    ("users", "phone_verified_at", "REAL"),
    ("users", "phone_pending", "TEXT"),
    ("users", "phone_code_sent_at", "REAL"),
    ("agents", "oauth_client_id", "TEXT"),
    ("grants", "source", "TEXT NOT NULL DEFAULT 'gmail'"),
    ("agents", "mode", "TEXT NOT NULL DEFAULT 'standard'"),
    ("users", "offline_start", "INTEGER"),
    ("users", "offline_end", "INTEGER"),
    ("users", "timezone", "TEXT"),
    ("grants", "task_id", "TEXT"),
    ("tasks", "questions", "TEXT"),
    ("tasks", "merged_into", "TEXT"),
    ("grants", "account", "TEXT"),
    # The accounts a grant reads (connection ids); NULL means every active account of its kind.
    ("grants", "account_ids", "TEXT"),
]
INDEXES_ON_ADDED = [
    "CREATE INDEX IF NOT EXISTS agents_user ON agents(user_id)",
    "CREATE INDEX IF NOT EXISTS connections_user ON connections(user_id, provider, status)",
    "CREATE INDEX IF NOT EXISTS grants_source ON grants(agent_id, source, created_at)",
    "CREATE INDEX IF NOT EXISTS grants_task ON grants(task_id)",
]

JSON_COLUMNS = {"scopes", "signals", "detail", "questions", "tools", "account_ids"}
# Tables whose primary key isn't an `id` column.
KEYED_ELSEWHERE = {"grant_messages", "oauth_clients", "oauth_codes", "oauth_tokens"}

_lock = threading.Lock()
_conn: Any = None


def _connect() -> Any:
    s = settings()
    if s.turso_database_url:
        return libsql.connect(s.turso_database_url, auth_token=s.turso_auth_token or "")
    return libsql.connect(s.local_db_path)


def _run(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        try:
            cur = _conn.execute(sql, tuple(params))
        except ValueError as e:
            # Remote streams expire when idle; reconnect once.
            if "stream" not in str(e).lower():
                raise
            _conn = _connect()
            cur = _conn.execute(sql, tuple(params))
        _conn.commit()
        if not cur.description:
            return []
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            for c in JSON_COLUMNS & row.keys():
                if isinstance(row[c], str):
                    row[c] = json.loads(row[c])
            rows.append(row)
        return rows


async def q(sql: str, *params: Any) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_run, sql, params)


async def one(sql: str, *params: Any) -> dict[str, Any] | None:
    rows = await q(sql, *params)
    return rows[0] if rows else None


async def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    row = {"id": new_id(), **row} if "id" not in row and table not in KEYED_ELSEWHERE else row
    cols = list(row)
    vals = [json.dumps(v) if c in JSON_COLUMNS and v is not None else v for c, v in row.items()]
    await q(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", *vals)
    return row


async def update(table: str, id_: str, **fields: Any) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = [json.dumps(v) if k in JSON_COLUMNS and v is not None else v for k, v in fields.items()]
    await q(f"UPDATE {table} SET {sets} WHERE id = ?", *vals, id_)


async def migrate() -> None:
    for stmt in SCHEMA:
        await q(stmt)
    for table, column, kind in ADDED_COLUMNS:
        existing = {r["name"] for r in await q(f"PRAGMA table_info({table})")}
        if column not in existing:
            await q(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    for stmt in INDEXES_ON_ADDED:
        await q(stmt)


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()
