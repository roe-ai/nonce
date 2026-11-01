"""Your own MCP servers and HTTP APIs, tunneled through nonce.

You add a server's URL and (optionally) the header it needs. nonce keeps the header encrypted,
lists the server's tools, and makes every call itself, under the same grants, approvals and
checks as Gmail or Slack. Apps never see the URL's credentials.

Each tool has a rule: "auto" (nonce decides, like any request), "ask" (you approve every
grant that includes it; the default for tools that can change things) or "off".
"""

import asyncio
import ipaddress
import json
import socket
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal
from urllib.parse import urlsplit

import anyio
import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from . import db
from .config import settings
from .crypto import decrypt, encrypt
from .errors import AccessError
from .signals import Detector
from .policy import is_injection
from .sources import CONNECTOR_PREFIX, Source, custom_source

Kind = Literal["mcp", "http"]
Rule = Literal["auto", "ask", "off"]

CALL_TIMEOUT_S = 30.0
OUTPUT_MAX = 20_000
DESCRIPTION_MAX = 500
ARGS_SHOWN = 500
MAX_TOOLS = 100

# An HTTP API gets two tools: reading, and anything that changes something.
HTTP_TOOLS = [
    {
        "name": "get",
        "description": "GET a path on this API, e.g. /v1/orders?status=open. Returns the status and body.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        "read_only": True,
    },
    {
        "name": "send",
        "description": "POST, PUT, PATCH or DELETE a path on this API with an optional JSON body.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["POST", "PUT", "PATCH", "DELETE"]},
                "path": {"type": "string"},
                "body": {"type": "object"},
            },
            "required": ["method", "path"],
        },
        "read_only": False,
    },
]

# Tests point a URL at an in-process MCP server or a mock HTTP transport.
_mcp_overrides: dict[str, Any] = {}
_http_transport: httpx.AsyncBaseTransport | None = None


def use_mcp_server(url: str, server: Any | None) -> None:
    if server is None:
        _mcp_overrides.pop(url, None)
    else:
        _mcp_overrides[url] = server


def use_http_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _http_transport
    _http_transport = transport


# ---------------------------------------------------------------------------
# URLs: only public https hosts, so a connector can't reach nonce's own network.


def _dev_local(host: str) -> bool:
    return not settings().production and host in ("localhost", "127.0.0.1", "::1")


async def check_url(url: str) -> None:
    if url in _mcp_overrides or (_http_transport and url.startswith("https://")):
        return
    u = urlsplit(url)
    host = u.hostname or ""
    if not host:
        raise AccessError("bad_url", "Enter a full URL, like https://example.com/mcp", 400)
    if u.username or u.password:
        raise AccessError("bad_url", "Put the password or token in the header field, not in the URL", 400)
    if u.scheme != "https" and not (u.scheme == "http" and _dev_local(host)):
        raise AccessError("bad_url", "Use an https:// URL", 400)
    if _dev_local(host):
        return
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise AccessError("bad_url", f"Couldn't find {host}", 400) from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise AccessError("bad_url", f"{host} points to a private network address, which nonce won't call", 400)


# ---------------------------------------------------------------------------
# Storage


def _headers(row: dict) -> dict[str, str]:
    return json.loads(decrypt(row["auth_enc"])) if row.get("auth_enc") else {}


def public(row: dict) -> dict:
    """What the dashboard sees: never the header's value."""
    return {
        "id": row["id"],
        "source": CONNECTOR_PREFIX + row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "url": row["url"],
        "auth_header": row.get("auth_header"),
        "status": row["status"],
        "tools": row["tools"] or [],
        "error": row.get("error"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def as_source(row: dict) -> Source:
    tools = [t for t in row["tools"] or [] if t["rule"] != "off"]
    return custom_source(
        CONNECTOR_PREFIX + row["id"],
        row["name"],
        frozenset(t["name"] for t in tools),
        frozenset(t["name"] for t in tools if t["rule"] == "ask"),
    )


def connector_id(source_id: str) -> str:
    return source_id.removeprefix(CONNECTOR_PREFIX)


async def get(source_or_id: str) -> dict | None:
    return await db.one("SELECT * FROM connectors WHERE id = ? AND status != 'removed'", connector_id(source_or_id))


async def owned(user_id: str, connector_id_: str) -> dict:
    row = await get(connector_id_)
    if not row or row["user_id"] != user_id:
        raise AccessError("not_found", "Not found", 404)
    return row


async def for_user(user_id: str) -> list[dict]:
    rows = await db.q("SELECT * FROM connectors WHERE user_id = ? AND status != 'removed' ORDER BY created_at", user_id)
    for r in rows:
        as_source(r)
    return rows


async def for_agents(user_id: str) -> list[dict]:
    """The user's connectors as an app sees them: tools it may ask for, never credentials."""
    out = []
    for row in await for_user(user_id):
        if row["status"] != "active":
            continue
        tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
                "needs_approval": t["rule"] == "ask",
            }
            for t in row["tools"] or []
            if t["rule"] != "off"
        ]
        if tools:
            out.append({"source": CONNECTOR_PREFIX + row["id"], "label": row["name"], "tools": tools})
    return out


# ---------------------------------------------------------------------------
# Talking to the server


@asynccontextmanager
async def _mcp(row: dict) -> AsyncIterator[Client]:
    if override := _mcp_overrides.get(row["url"]):
        async with Client(override, cache=None) as client:
            yield client
        return
    await check_url(row["url"])
    http = create_mcp_http_client(headers=_headers(row), timeout=httpx2.Timeout(CALL_TIMEOUT_S))
    async with http, Client(streamable_http_client(row["url"], http_client=http), cache=None) as client:
        yield client


def _upstream_error(row: dict, e: Exception) -> AccessError:
    msg = str(e).strip().splitlines()[0][:200] if str(e).strip() else type(e).__name__
    return AccessError("upstream_error", f"{row['name']} didn't answer: {msg}", 502)


async def _list_mcp_tools(row: dict) -> list[dict]:
    tools: list[dict] = []
    try:
        with anyio.fail_after(CALL_TIMEOUT_S):
            async with _mcp(row) as client:
                cursor = None
                for _ in range(10):
                    page = await client.list_tools(cursor=cursor)
                    for t in page.tools:
                        hint = t.annotations.read_only_hint if t.annotations else None
                        tools.append(
                            {
                                "name": t.name,
                                "description": (t.description or "").strip()[:DESCRIPTION_MAX],
                                "input_schema": t.input_schema,
                                "read_only": bool(hint),
                            }
                        )
                    cursor = page.next_cursor
                    if not cursor or len(tools) >= MAX_TOOLS:
                        break
    except AccessError:
        raise
    except Exception as e:
        raise _upstream_error(row, e) from e
    return tools[:MAX_TOOLS]


async def discover(row: dict, detector: Detector, previous: list[dict] | None = None) -> list[dict]:
    """The server's tools, with your earlier rules kept. Descriptions that coach AI apps are hidden and the tool is off."""
    found = HTTP_TOOLS if row["kind"] == "http" else await _list_mcp_tools(row)
    rules = {t["name"]: t["rule"] for t in previous or []}

    async def checked(t: dict) -> dict:
        tool = {**t, "suspicious": False}
        if t["description"] and row["kind"] == "mcp":
            signals = await detector.content({"data_source": row["name"], "title": f"Tool {t['name']}", "text": t["description"]})
            if is_injection(signals):
                tool.update(description="", suspicious=True)
        default: Rule = "off" if tool["suspicious"] else "auto" if t["read_only"] else "ask"
        tool["rule"] = rules.get(t["name"], default)
        return tool

    return list(await asyncio.gather(*(checked(t) for t in found)))


def _text(result: Any) -> str:
    parts = []
    for block in result.content:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind == "resource" and getattr(block.resource, "text", None):
            parts.append(block.resource.text)
        else:
            parts.append(f"[{kind or 'content'} omitted]")
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content))
    return "\n".join(parts)


async def _call_mcp(row: dict, tool: str, arguments: dict) -> tuple[str, bool]:
    try:
        with anyio.fail_after(CALL_TIMEOUT_S):
            async with _mcp(row) as client:
                result = await client.call_tool(tool, arguments)
    except AccessError:
        raise
    except Exception as e:
        raise _upstream_error(row, e) from e
    return _text(result), bool(result.is_error)


async def _call_http(row: dict, tool: str, arguments: dict) -> tuple[str, bool]:
    path = str(arguments.get("path") or "")
    if not path.startswith("/") or path.startswith("//") or "\\" in path or "/../" in f"{path}/" or "@" in path.split("?")[0]:
        raise AccessError("bad_request", "path must be a path on this API, starting with /", 400)
    base = row["url"].rstrip("/")
    url = base + path
    if urlsplit(url).netloc != urlsplit(base).netloc:
        raise AccessError("bad_request", "path must stay on this API", 400)
    method = "GET" if tool == "get" else str(arguments.get("method") or "").upper()
    if tool == "send" and method not in ("POST", "PUT", "PATCH", "DELETE"):
        raise AccessError("bad_request", "method must be POST, PUT, PATCH or DELETE", 400)
    await check_url(base)
    body = arguments.get("body") if method != "GET" else None
    try:
        async with httpx.AsyncClient(transport=_http_transport, follow_redirects=False, timeout=CALL_TIMEOUT_S) as client:
            res = await client.request(method, url, headers=_headers(row), json=body)
    except httpx.HTTPError as e:
        raise _upstream_error(row, e) from e
    return f"HTTP {res.status_code}\n{res.text}", res.status_code >= 400


async def call(row: dict, tool: str, arguments: dict) -> tuple[str, bool]:
    text, is_error = await (_call_http if row["kind"] == "http" else _call_mcp)(row, tool, arguments)
    if len(text) > OUTPUT_MAX:
        text = text[:OUTPUT_MAX] + f"\n[Cut by nonce: {len(text) - OUTPUT_MAX} more characters]"
    return text, is_error


# ---------------------------------------------------------------------------
# Managing connectors (dashboard)


async def add(user_id: str, *, name: str, kind: Kind, url: str, auth_header: str | None, auth_value: str | None, detector: Detector) -> dict:
    url = url.strip()
    await check_url(url)
    headers = {auth_header.strip(): auth_value} if auth_header and auth_value else {}
    now = db.now()
    row = {
        "user_id": user_id,
        "name": name.strip(),
        "kind": kind,
        "url": url,
        "auth_header": auth_header.strip() if headers and auth_header else None,
        "auth_enc": encrypt(json.dumps(headers)) if headers else None,
        "status": "active",
        "tools": [],
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    row["tools"] = await discover(row, detector)
    row = await db.insert("connectors", row)
    # Grants point at a connection; the connector's has the same id and no credentials of its own.
    await db.insert(
        "connections",
        {"id": row["id"], "user_id": user_id, "provider": "connector", "mode": kind, "account": row["name"], "status": "active", "created_at": now},
    )
    return row


async def refresh(row: dict, detector: Detector) -> dict:
    try:
        tools = await discover(row, detector, row["tools"])
    except AccessError as e:
        await db.update("connectors", row["id"], error=e.message, updated_at=db.now())
        raise
    await db.update("connectors", row["id"], tools=tools, error=None, updated_at=db.now())
    return {**row, "tools": tools, "error": None}


async def set_rule(row: dict, tool: str, rule: Rule) -> dict:
    tools = row["tools"] or []
    if not any(t["name"] == tool for t in tools):
        raise AccessError("not_found", f"{row['name']} has no tool '{tool}'", 404)
    tools = [{**t, "rule": rule} if t["name"] == tool else t for t in tools]
    await db.update("connectors", row["id"], tools=tools, updated_at=db.now())
    return {**row, "tools": tools}


def args_shown(arguments: dict) -> str:
    text = json.dumps(arguments, ensure_ascii=False)
    return text if len(text) <= ARGS_SHOWN else text[:ARGS_SHOWN] + "…"
