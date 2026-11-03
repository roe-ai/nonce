"""Plain-language filters for text messages and the approval page (mirrors web/lib/humanize.ts)."""

import re

from .errors import AccessError
from .filters import parse
from .sources import source

TYPE_WORDS = {"doc": "docs", "sheet": "spreadsheets", "slides": "slide decks", "pdf": "PDFs", "folder": "folders", "image": "images"}


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} or {xs[-1]}"


def _dates(after, before) -> str:
    fmt = lambda d: d.strftime("%b %-d, %Y")  # noqa: E731
    if after and before:
        return f"between {fmt(after)} and {fmt(before)}"
    if after:
        return f"after {fmt(after)}"
    return f"before {fmt(before)}" if before else ""


def _gmail(q: str) -> str:
    if re.search(r"in:(anywhere|all)", q, re.I):
        return "your entire inbox"
    senders, subjects, words = [], [], []
    for tok in re.findall(r'"[^"]*"|\S+', q.replace("(", " ").replace(")", " ")):
        if tok.upper() == "OR":
            continue
        field, _, val = tok.strip('"').partition(":")
        if val and field.lower() == "from":
            senders.append(val)
        elif val and field.lower() == "subject":
            subjects.append(f"“{val}”")
        elif not val:
            words.append(tok.strip('"'))
    parts = []
    if senders:
        parts.append(f"from {_join(senders)}")
    if subjects:
        parts.append(f"with {_join(subjects)} in the subject")
    if words:
        parts.append(f"about {' '.join(words)}")
    return f"emails {' '.join(parts)}" if parts else "some of your emails"


def _structured(q: str, src_id: str) -> str:
    keys = {"calendar": {"with"}, "drive": {"name", "type", "owner"}, "slack": {"in", "from", "has", "is"}}[src_id]
    try:
        f = parse(q, keys)
    except AccessError:
        return f"some of your {source(src_id).items}"
    noun = source(src_id).items
    if src_id == "drive" and f.values("type"):
        noun = _join([TYPE_WORDS.get(t.lower(), t) for t in f.values("type")])
    parts = [noun]
    if f.values("name"):
        parts.append(f"named {_join([f'“{n}”' for n in f.values('name')])}")
    if f.values("in"):
        parts.append(f"in {_join(['#' + c.lstrip('#') for c in f.values('in')])}")
    if f.values("from"):
        parts.append(f"from {_join([p.lstrip('@') for p in f.values('from')])}")
    if f.values("with"):
        parts.append(f"with {_join(f.values('with'))}")
    if f.values("owner"):
        parts.append(f"owned by {_join(f.values('owner'))}")
    if f.words:
        parts.append(f"about {' '.join(f.words)}")
    if when := _dates(f.after, f.before):
        parts.append(("modified " if src_id == "drive" else "") + when)
    return " ".join(parts) if len(parts) > 1 or noun != source(src_id).items else f"some of your {noun}"


def describe_filter(q: str | None, src_id: str | None = "gmail") -> str:
    src = source(src_id)
    if not q or not q.strip():
        return src.whole
    if src.custom:
        return q.strip()
    return _gmail(q) if src.id == "gmail" else _structured(q, src.id)
