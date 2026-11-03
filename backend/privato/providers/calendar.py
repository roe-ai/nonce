"""Google Calendar (primary calendar), read-only.

Calendar's own search is loose, so Privato asks Google for the date window and checks
every word and attendee filter itself before an agent sees an event.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

from ..filters import Filter, combine, contains_all, parse
from .google import service

KEYS = {"with"}
# Without dates in the filter, search a year back and a year ahead.
DEFAULT_REACH = timedelta(days=365)
MAX_SCANNED = 1000


@dataclass
class Event:
    id: str
    title: str
    start: str
    end: str
    all_day: bool
    organizer: str = ""
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    description: str = ""
    link: str = ""

    CONTENT_FIELDS: ClassVar[tuple[str, ...]] = ("description",)

    def view(self, scopes: list[str], *, full: bool = False) -> dict:
        d = {"id": self.id, "title": self.title, "start": self.start, "end": self.end, "all_day": self.all_day}
        if "calendar.details" in scopes:
            d.update(organizer=self.organizer, location=self.location, attendees=self.attendees, link=self.link)
            if full:
                d["description"] = self.description
        return d

    def for_check(self) -> dict[str, str]:
        return {"author": self.organizer, "title": self.title, "text": f"{self.location}\n{self.description}"[:4000]}

    def matches(self, f: Filter) -> bool:
        people = " ".join([self.organizer, *self.attendees])
        return contains_all(f"{self.title} {self.description} {self.location} {people}", f.words) and all(
            contains_all(people, [w]) for w in f.values("with")
        )


def check_filter(q: str) -> None:
    parse(q, KEYS)


def _when(t: dict) -> tuple[str, bool]:
    return (t["date"], True) if "date" in t else (t.get("dateTime", ""), False)


def _event(e: dict) -> Event:
    start, all_day = _when(e.get("start", {}))
    end, _ = _when(e.get("end", {}))
    org = e.get("organizer", {})
    return Event(
        id=e["id"],
        title=e.get("summary", "(no title)"),
        start=start,
        end=end,
        all_day=all_day,
        organizer=org.get("displayName") or org.get("email", ""),
        location=e.get("location", ""),
        attendees=[a.get("displayName") or a.get("email", "") for a in e.get("attendees", [])],
        description=e.get("description", ""),
        link=e.get("htmlLink", ""),
    )


def _rfc3339(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()


def rank(events: list[Event], now: str) -> list[Event]:
    """Upcoming events soonest first, then past events most recent first."""
    upcoming = sorted((e for e in events if e.start >= now[: len(e.start)]), key=lambda e: e.start)
    past = sorted((e for e in events if e.start < now[: len(e.start)]), key=lambda e: e.start, reverse=True)
    return upcoming + past


class GoogleCalendar:
    def __init__(self, credentials_enc: str):
        self.credentials_enc = credentials_enc

    def _service(self):
        return service(self.credentials_enc, "calendar", "calendar", "v3")

    async def search(self, constraint: str, query: str, limit: int) -> list[Event]:
        f = combine(constraint, query, KEYS)
        today = datetime.now(UTC).date()
        start, end = f.after or today - DEFAULT_REACH, f.before or today + DEFAULT_REACH
        if start >= end:
            return []

        def run() -> list[Event]:
            svc = self._service()
            found: list[Event] = []
            page, scanned = None, 0
            while scanned < MAX_SCANNED:
                res = (
                    svc.events()
                    .list(
                        calendarId="primary",
                        timeMin=_rfc3339(start),
                        timeMax=_rfc3339(end),
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=250,
                        pageToken=page,
                        q=max(f.words, key=len) if f.words else None,
                    )
                    .execute()
                )
                items = res.get("items", [])
                scanned += len(items)
                found += [e for e in map(_event, items) if e.matches(f)]
                page = res.get("nextPageToken")
                if not page:
                    break
            return rank(found, datetime.now(UTC).isoformat())[:limit]

        return await asyncio.to_thread(run)

    async def get(self, item_id: str, *, content: bool = True) -> Event | None:
        return await asyncio.to_thread(lambda: _event(self._service().events().get(calendarId="primary", eventId=item_id).execute()))
