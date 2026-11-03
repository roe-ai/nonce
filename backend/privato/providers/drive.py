"""Google Drive, read-only. Privato compiles the grant's filter and the agent's search into one
Drive query joined with `and`, quoting every value, so an agent can't inject `or`."""

import asyncio
from dataclasses import dataclass
from typing import ClassVar

from ..errors import AccessError
from ..filters import Filter, combine, parse
from .google import service

KEYS = {"name", "type", "owner"}
MAX_CHARS = 100_000

MIME = {
    "doc": "application/vnd.google-apps.document",
    "sheet": "application/vnd.google-apps.spreadsheet",
    "slides": "application/vnd.google-apps.presentation",
    "folder": "application/vnd.google-apps.folder",
    "pdf": "application/pdf",
}
EXPORT = {MIME["doc"]: "text/plain", MIME["sheet"]: "text/csv", MIME["slides"]: "text/plain"}
FIELDS = "id, name, mimeType, modifiedTime, owners(displayName, emailAddress), webViewLink"


@dataclass
class File:
    id: str
    name: str
    type: str
    modified: str
    owner: str
    link: str
    content: str = ""

    CONTENT_FIELDS: ClassVar[tuple[str, ...]] = ("content",)

    @property
    def title(self) -> str:
        return self.name

    def view(self, scopes: list[str], *, full: bool = False) -> dict:
        d = {"id": self.id, "name": self.name, "type": self.type, "modified": self.modified, "owner": self.owner, "link": self.link}
        if full and "drive.content" in scopes:
            d["content"] = self.content
        return d

    def for_check(self) -> dict[str, str]:
        return {"author": self.owner, "title": self.name, "text": self.content[:4000]}


def check_filter(q: str) -> None:
    f = parse(q, KEYS)
    for t in f.values("type"):
        if t.lower() not in {*MIME, "image"}:
            raise AccessError("bad_query", f"Unknown type:{t}. Use doc, sheet, slides, pdf, folder or image")


def _quote(v: str) -> str:
    return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"


def compile_query(f: Filter) -> str:
    parts = ["trashed = false"]
    parts += [f"fullText contains {_quote(w)}" for w in f.words]
    parts += [f"name contains {_quote(n)}" for n in f.values("name")]
    for t in f.values("type"):
        t = t.lower()
        parts.append("mimeType contains 'image/'" if t == "image" else f"mimeType = {_quote(MIME[t])}")
    parts += [f"{_quote(o)} in owners" for o in f.values("owner")]
    if f.after:
        parts.append(f"modifiedTime > '{f.after.isoformat()}T00:00:00'")
    if f.before:
        parts.append(f"modifiedTime < '{f.before.isoformat()}T00:00:00'")
    return " and ".join(parts)


def _kind(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    return next((k for k, v in MIME.items() if v == mime), "file")


def _file(d: dict, content: str = "") -> File:
    owner = (d.get("owners") or [{}])[0]
    return File(
        id=d["id"],
        name=d.get("name", ""),
        type=_kind(d.get("mimeType", "")),
        modified=d.get("modifiedTime", ""),
        owner=owner.get("emailAddress") or owner.get("displayName", ""),
        link=d.get("webViewLink", ""),
        content=content,
    )


class GoogleDrive:
    def __init__(self, credentials_enc: str):
        self.credentials_enc = credentials_enc

    def _service(self):
        return service(self.credentials_enc, "drive", "drive", "v3")

    async def search(self, constraint: str, query: str, limit: int) -> list[File]:
        check_filter(constraint)
        check_filter(query)
        f = combine(constraint, query, KEYS)
        q = compile_query(f)

        def run() -> list[File]:
            params = {"q": q, "pageSize": limit, "fields": f"files({FIELDS})", "spaces": "drive"}
            if not f.words:  # Drive can't sort full-text results
                params["orderBy"] = "modifiedTime desc"
            return [_file(d) for d in self._service().files().list(**params).execute().get("files", [])]

        return await asyncio.to_thread(run)

    async def get(self, item_id: str, *, content: bool = True) -> File | None:
        def run() -> File:
            svc = self._service()
            meta = svc.files().get(fileId=item_id, fields=FIELDS + ", size").execute()
            if not content:
                return _file(meta)
            mime = meta.get("mimeType", "")
            if mime in EXPORT:
                raw = svc.files().export(fileId=item_id, mimeType=EXPORT[mime]).execute()
            elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
                raw = svc.files().get_media(fileId=item_id).execute()
            else:
                return _file(meta, f"[Privato can't read the text of this kind of file yet ({mime}).]")
            text = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
            return _file(meta, text[:MAX_CHARS])

        return await asyncio.to_thread(run)
