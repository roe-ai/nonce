"""An in-memory Gmail for tests: a small Gmail query evaluator over tests/fake_inbox.py."""

import shlex

from privato.providers.gmail import Message

from fake_inbox import INBOX


def _terms(q: str) -> list[list[str]]:
    """Gmail-ish query → AND of OR-groups. `a OR b c` is (a OR b) AND c."""
    try:
        toks = shlex.split(q.replace("(", " ").replace(")", " "))
    except ValueError:
        toks = q.split()
    groups: list[list[str]] = []
    join = False
    for t in toks:
        if t.upper() == "OR":
            join = True
            continue
        if join and groups:
            groups[-1].append(t)
        else:
            groups.append([t])
        join = False
    return groups


def _match_term(m: Message, term: str) -> bool:
    neg = term.startswith("-")
    term = term.lstrip("-").lower()
    if ":" in term:
        field, _, val = term.partition(":")
        hay = {"from": m.sender, "to": m.to, "subject": m.subject}.get(field)
        hit = True if hay is None else val in hay.lower()  # after:, label: etc. are not modelled
    else:
        hit = term in f"{m.sender} {m.subject} {m.body}".lower()
    return hit != neg


def _matches(m: Message, q: str) -> bool:
    return all(any(_match_term(m, t) for t in group) for group in _terms(q))


class FakeGmail:
    def __init__(self, messages: list[dict] | None = None):
        self.messages = [Message(**d) for d in (messages or INBOX)]

    async def search(self, constraint: str, query: str, limit: int) -> list[Message]:
        hits = [m for m in self.messages if _matches(m, constraint) and _matches(m, query)]
        return sorted(hits, key=lambda m: m.date, reverse=True)[:limit]

    async def get(self, message_id: str, *, content: bool = True) -> Message | None:
        return next((m for m in self.messages if m.id == message_id), None)


