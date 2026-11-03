"""Gmail through the real API, with the user's OAuth refresh token.

Privato never hands Gmail credentials to agents. Every search runs as
`(grant constraint) (agent query)`, so an agent can narrow a grant but never widen it.
"""

import asyncio
import base64
import re
from dataclasses import asdict, dataclass
from typing import ClassVar

from .google import SCOPES, service

GMAIL_SCOPE = SCOPES["gmail"]


@dataclass
class Message:
    id: str
    thread_id: str
    sender: str
    to: str
    subject: str
    date: str
    snippet: str = ""
    body: str = ""

    CONTENT_FIELDS: ClassVar[tuple[str, ...]] = ("body", "snippet")

    @property
    def title(self) -> str:
        return self.subject

    def view(self, scopes: list[str], *, full: bool = False) -> dict:
        """Search results never carry bodies: only gmail_read does, after the injection check."""
        d = asdict(self)
        if not full:
            d.pop("body")
        if "gmail.body" not in scopes:
            d.pop("snippet")
            d.pop("body", None)
        return d

    def for_check(self) -> dict[str, str]:
        return {"author": self.sender, "title": self.subject, "text": self.body[:4000]}


class GoogleGmail:
    def __init__(self, credentials_enc: str):
        self.credentials_enc = credentials_enc

    def _service(self):
        return service(self.credentials_enc, "gmail", "gmail", "v1")

    async def search(self, constraint: str, query: str, limit: int) -> list[Message]:
        def run() -> list[Message]:
            svc = self._service()
            q = f"({constraint}) ({query})" if query.strip() else f"({constraint})"
            res = svc.users().messages().list(userId="me", q=q, maxResults=limit).execute()
            return [self._fetch(svc, r["id"], full=False) for r in res.get("messages", [])]

        return await asyncio.to_thread(run)

    async def get(self, item_id: str, *, content: bool = True) -> Message | None:
        return await asyncio.to_thread(lambda: self._fetch(self._service(), item_id, full=True))

    @staticmethod
    def _fetch(svc, message_id: str, full: bool) -> Message:
        fmt = "full" if full else "metadata"
        m = svc.users().messages().get(userId="me", id=message_id, format=fmt).execute()
        headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        return Message(
            id=m["id"],
            thread_id=m["threadId"],
            sender=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", ""),
            date=headers.get("date", ""),
            snippet=m.get("snippet", ""),
            body=_plain_text(m["payload"]) if full else "",
        )


def _plain_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
    for part in payload.get("parts", []) or []:
        if text := _plain_text(part):
            return text
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        html = base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
        return re.sub(r"<[^>]+>", " ", html)
    return ""
