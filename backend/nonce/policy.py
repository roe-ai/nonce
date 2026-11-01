"""Decisions from fixed rules plus signals (signals.py). Pure functions, so tests need no network.

Each app has a mode. Modes move the "ask you" thresholds; the hard limits (deny) are the
same in every mode, so Relaxed never lets an app take everything.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from .config import settings
from .signals import SENSITIVE
from .sources import Source

ModeName = Literal["cautious", "standard", "relaxed"]

# Hard limits, every mode.
CRAWL_DENY = 2.5
INJECTION_MIN = 0.5
SERVES_REVOKE_FLAGGED = 0.5
FAMILIAR_MIN = 0.5


@dataclass(frozen=True)
class Mode:
    name: ModeName
    user_initiated_min: float
    consistent_min: float
    scope_fits_min: float
    crawl_ask: float
    auto_ttl_factor: float  # × MAX_AUTO_TTL_S
    requests_factor: float  # × MAX_REQUESTS_PER_HOUR
    # A category the app hasn't used before asks once it has used this many (None: never asks).
    new_category_after: int | None
    # Finance and health go through without asking when the signals are this sure you asked (None: always ask).
    # Security (passwords, login codes) always asks.
    sensitive_ok_if_asked: float | None
    must_be_familiar: bool  # ask unless you've asked something like this before
    content_asks: bool  # ask before an app reads full text, not just titles and senders
    serves_revoke: float
    serves_warn: float


MODES: dict[str, Mode] = {
    "cautious": Mode("cautious", 0.7, 0.7, 0.7, 1.0, 0.25, 0.5, 0, None, True, True, 0.5, 0.7),
    "standard": Mode("standard", 0.5, 0.5, 0.5, 1.5, 1, 1, 3, None, False, False, 0.3, 0.5),
    "relaxed": Mode("relaxed", 0.3, 0.3, 0.3, 2.0, 4, 2.5, None, 0.8, False, False, 0.2, 0.35),
}


def mode(name: str | None) -> Mode:
    return MODES.get(name or "standard", MODES["standard"])


def human_duration(seconds: int) -> str:
    if seconds < 3600:
        m = max(1, seconds // 60)
        return f"{m} minute{'s' if m != 1 else ''}"
    h = seconds / 3600
    if h < 48:
        h = round(h)
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{round(h / 24)} days"


def sensitive_label(category: str, src: Source) -> str:
    return {
        "finance": f"your financial {src.items}",
        "health": f"your health {src.items}",
        "security": "your passwords and login codes",
    }[category]


@dataclass
class Decision:
    outcome: Literal["allow", "ask", "deny", "revoke", "warn"]
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return ". ".join(self.reasons)


@dataclass
class AccessContext:
    requests_last_hour: int
    known_categories: set[str]
    offline: bool  # inside the user's offline hours
    history_size: int = 0  # past requests you allowed, across your apps


def auto_ttl_s(m: Mode) -> int:
    return int(settings().max_auto_ttl_s * m.auto_ttl_factor)


def decide_access(
    *,
    src: Source,
    mode: Mode,
    scopes: list[str],
    constraint: str,
    ttl_s: int,
    signals: dict[str, Any] | None,
    ctx: AccessContext,
) -> Decision:
    s = settings()
    deny: list[str] = []
    ask: list[str] = []

    if unknown := set(scopes) - src.scopes:
        if src.custom:
            deny.append(f"It asked for tools in {src.label} that you turned off or that don't exist ({', '.join(sorted(unknown))})")
        else:
            deny.append(f"It asked for a kind of access nonce doesn't offer ({', '.join(sorted(unknown))})")
    if ttl_s > s.hard_max_ttl_s:
        deny.append(f"It wanted access for {human_duration(ttl_s)}, longer than nonce ever allows")
    if signals and signals.get("crawl", 0) >= CRAWL_DENY:
        deny.append(f"It tried to collect {src.whole}")
    if deny:
        return Decision("deny", deny)

    if not constraint.strip():
        ask.append(f"It wants {src.whole}, not specific {src.items}")
    if ttl_s > auto_ttl_s(mode):
        ask.append(f"It wants access for {human_duration(ttl_s)}")
    if ctx.requests_last_hour >= s.max_requests_per_hour * mode.requests_factor:
        ask.append(f"It has asked {ctx.requests_last_hour} times in the last hour")
    if ctx.offline:
        ask.append("It asked during your offline hours")
    if risky := sorted(src.ask_tools & set(scopes)):
        ask.append(f"It wants to use {', '.join(risky)} in {src.label}, which you approve yourself")
    if mode.content_asks and src.content_scope in scopes:
        ask.append(f"It wants to read whole {src.items}, not just what they're about")

    if signals is None:
        ask.append("We couldn't check this request automatically")
    else:
        if signals["user_initiated"] < mode.user_initiated_min:
            ask.append("The app is acting on its own, not because you asked")
        if signals["consistent"] < mode.consistent_min:
            ask.append("Its reason doesn't match what you asked")
        if signals["scope_fits"] < mode.scope_fits_min:
            ask.append(f"It wants more {src.items} than your question needs")
        if signals["crawl"] >= mode.crawl_ask:
            ask.append(f"It wants a lot of your {src.items}")
        category = signals.get("category")
        if category in SENSITIVE:
            clearly_asked = mode.sensitive_ok_if_asked is not None and signals["user_initiated"] >= mode.sensitive_ok_if_asked
            if category == "security" or not clearly_asked:
                ask.append(f"It wants {sensitive_label(category, src)}")
        if mode.new_category_after is not None and len(ctx.known_categories) >= mode.new_category_after and category not in ctx.known_categories:
            ask.append(f"It has never asked for {category} {src.items} before")
        if mode.must_be_familiar:
            if ctx.history_size == 0:
                ask.append("This is the first thing you've let an app look up")
            elif signals.get("familiar", 0) < FAMILIAR_MIN:
                ask.append("You haven't asked anything like this lately")

    return Decision("ask", ask) if ask else Decision("allow", ["Matches what you asked"])


def decide_search(
    *,
    src: Source,
    mode: Mode,
    grant: dict[str, Any],
    searches_last_minute: int,
    signals: dict[str, Any] | None,
) -> Decision:
    s = settings()
    if searches_last_minute >= s.max_searches_per_minute:
        return Decision("revoke", [f"It searched your {src.items} too many times, too fast"])
    if signals is None:
        return Decision("allow", ["Within the access you gave (not checked automatically)"])

    flagged = bool((grant.get("signals") or {}).get("injection_seen"))
    revoke: list[str] = []
    if signals["serves"] < (max(SERVES_REVOKE_FLAGGED, mode.serves_revoke) if flagged else mode.serves_revoke):
        revoke.append("It searched for something unrelated to what you asked")
    if signals["crawl"] >= CRAWL_DENY:
        revoke.append(f"It tried to collect {src.whole}")
    category = signals.get("category")
    if category in SENSITIVE and category != grant.get("category"):
        revoke.append(f"It went after {sensitive_label(category, src)}")
    if revoke:
        return Decision("revoke", revoke)
    if signals["serves"] < mode.serves_warn:
        return Decision("warn", ["This search is only loosely related to what you asked"])
    return Decision("allow", ["Within the access you gave"])


def is_injection(signals: dict[str, Any] | None) -> bool:
    return bool(signals and signals.get("injection", 0) >= INJECTION_MIN)


def is_offline(hour: int, start: int | None, end: int | None) -> bool:
    """Offline hours wrap past midnight (23 → 7). start == end means never offline."""
    if start is None or end is None or start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end
