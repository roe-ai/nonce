"""Slack, through a user token with read-only search and history scopes.

Slack's search already ANDs terms and has no OR, so Privato sends `constraint query`.
In case Slack ever treats repeated `in:` or `from:` loosely, Privato also checks the
channel, author and dates of every result against both filters before an agent sees it.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

import httpx

from ..crypto import decrypt
from ..errors import AccessError
from ..filters import Filter, combine, parse

KEYS = {"in", "from", "has", "is"}
API = "https://slack.com/api"
SNIPPET = 200


@dataclass
class SlackMessage:
    id: str  # "<channel id>:<ts>"
    channel: str
    author: str
    date: str
    link: str
    text: str = ""
    thread: list[dict] = field(default_factory=list)

    CONTENT_FIELDS: ClassVar[tuple[str, ...]] = ("text", "snippet", "thread")

    @property
    def title(self) -> str:
        return f"a message in #{self.channel}" if self.channel else "a Slack thread"

    def view(self, scopes: list[str], *, full: bool = False) -> dict:
        d = {"id": self.id, "channel": self.channel, "author": self.author, "date": self.date, "link": self.link}
        if "slack.content" in scopes:
            if full:
                d.update(text=self.text, thread=self.thread)
            else:
                d["snippet"] = self.text[:SNIPPET]
        return d

    def for_check(self) -> dict[str, str]:
        replies = "\n".join(r.get("text", "") for r in self.thread)
        return {"author": self.author, "title": self.title, "text": f"{self.text}\n{replies}"[:4000]}

    def matches(self, f: Filter) -> bool:
        day = self.date[:10]
        return (
            all(self.channel.lower() == c.lstrip("#").lower() for c in f.values("in"))
            and all(self.author.lower() == a.lstrip("@").lower() for a in f.values("from"))
            and (not f.after or day >= f.after.isoformat())
            and (not f.before or day <= f.before.isoformat())
        )


def check_filter(q: str) -> None:
    parse(q, KEYS)


def _iso(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


class Slack:
    def __init__(self, credentials_enc: str):
        self.token = json.loads(decrypt(credentials_enc))["access_token"]

    async def _call(self, method: str, **params) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(f"{API}/{method}", params=params, headers={"Authorization": f"Bearer {self.token}"})
        body = res.json()
        if not body.get("ok"):
            if body.get("error") in ("invalid_auth", "token_revoked", "account_inactive"):
                raise AccessError("no_connection", "Slack access was revoked. Ask the user to reconnect Slack in Privato.", 409)
            raise AccessError("provider_error", f"Slack said: {body.get('error', 'unknown error')}", 502)
        return body

    async def search(self, constraint: str, query: str, limit: int) -> list[SlackMessage]:
        check_filter(constraint)
        check_filter(query)
        f = combine(constraint, query, KEYS)
        body = await self._call("search.messages", query=f"{constraint} {query}".strip(), count=min(limit * 2, 100), sort="timestamp", highlight="false")
        found = []
        for m in body.get("messages", {}).get("matches", []):
            ch = m.get("channel") or {}
            msg = SlackMessage(
                id=f"{ch.get('id', '')}:{m['ts']}",
                channel=ch.get("name", ""),
                author=m.get("username") or m.get("user", ""),
                date=_iso(m["ts"]),
                link=m.get("permalink", ""),
                text=m.get("text", ""),
            )
            if msg.matches(f):
                found.append(msg)
        return found[:limit]

    async def get(self, item_id: str, *, content: bool = True) -> SlackMessage | None:
        channel, _, ts = item_id.partition(":")
        body = await self._call("conversations.replies", channel=channel, ts=ts, limit=50)
        msgs = body.get("messages", [])
        mine = next((m for m in msgs if m.get("ts") == ts), None)
        if not mine:
            return None
        link = await self._call("chat.getPermalink", channel=channel, message_ts=ts)
        return SlackMessage(
            id=item_id,
            channel="",
            author=mine.get("user", ""),
            date=_iso(ts),
            link=link.get("permalink", ""),
            text=mine.get("text", ""),
            thread=[{"author": m.get("user", ""), "date": _iso(m["ts"]), "text": m.get("text", "")} for m in msgs if m.get("ts") != ts],
        )
