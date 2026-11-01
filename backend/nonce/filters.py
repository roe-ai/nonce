"""Filters for sources without a safe native query language (Calendar, Drive), and checks for Slack.

A grant's filter and an agent's search are parsed separately and combined with AND:
every word must match, every field must match, and date windows intersect. nonce
builds the provider query itself, so a search can narrow a grant but never widen it.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from .errors import AccessError


@dataclass
class Filter:
    words: list[str] = field(default_factory=list)
    fields: dict[str, list[str]] = field(default_factory=dict)
    after: date | None = None
    before: date | None = None

    def values(self, key: str) -> list[str]:
        return self.fields.get(key, [])


def _date(key: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise AccessError("bad_query", f"{key}: needs a date like 2026-11-01, got '{value}'") from None


def parse(q: str, keys: set[str]) -> Filter:
    """`keys` are the field names this source understands, besides after: and before:."""
    f = Filter()
    for tok in re.findall(r'(?:[\w-]+:)?"[^"]*"|\S+', q or ""):
        key, sep, value = tok.partition(":")
        if sep and re.fullmatch(r"[\w-]+", key) and value:
            key, value = key.lower(), value.strip('"')
            if key in ("after", "before"):
                d = _date(key, value)
                if key == "after":
                    f.after = max(f.after, d) if f.after else d
                else:
                    f.before = min(f.before, d) if f.before else d
            elif key in keys:
                f.fields.setdefault(key, []).append(value)
            else:
                allowed = ", ".join(f"{k}:" for k in sorted(keys | {"after", "before"}))
                raise AccessError("bad_query", f"Unknown filter '{key}:'. Use words and {allowed}")
        else:
            word = tok.strip('"').strip()
            if word and word.upper() not in ("AND", "OR"):
                f.words.append(word)
    return f


def combine(constraint: str, query: str, keys: set[str]) -> Filter:
    a, b = parse(constraint, keys), parse(query, keys)
    out = Filter(words=a.words + b.words, fields={k: a.values(k) + b.values(k) for k in a.fields.keys() | b.fields.keys()})
    out.after = max(d for d in (a.after, b.after) if d) if a.after or b.after else None
    out.before = min(d for d in (a.before, b.before) if d) if a.before or b.before else None
    return out


def contains_all(haystack: str, needles: list[str]) -> bool:
    text = haystack.lower()
    return all(n.lower() in text for n in needles)
