"""The kinds of data an app can ask for, and the words used for each in messages to the user."""

from dataclasses import dataclass
from typing import Literal

SourceId = Literal["gmail", "calendar", "drive", "slack"]


@dataclass(frozen=True)
class Source:
    id: str
    label: str  # "Google Calendar"
    item: str  # "event"
    items: str  # "events"
    whole: str  # "your whole calendar"
    wants: str  # "see your calendar", as in "Claude wants to see your calendar"
    metadata_scope: str
    content_scope: str
    syntax: str  # filter syntax, for agents
    # A connector the user added (their own MCP server or API): scopes are its tool names.
    custom: bool = False
    tools: frozenset[str] = frozenset()
    ask_tools: frozenset[str] = frozenset()  # tools the user approves every time

    @property
    def scopes(self) -> set[str]:
        return set(self.tools) if self.custom else {self.metadata_scope, self.content_scope}


SOURCES: dict[str, Source] = {
    s.id: s
    for s in [
        Source(
            id="gmail",
            label="Gmail",
            item="email",
            items="emails",
            whole="your entire inbox",
            wants="read your email",
            metadata_scope="gmail.metadata",
            content_scope="gmail.body",
            syntax="Gmail search syntax, e.g. 'from:united.com Tokyo'.",
        ),
        Source(
            id="calendar",
            label="Google Calendar",
            item="event",
            items="events",
            whole="your whole calendar",
            wants="see your calendar",
            metadata_scope="calendar.metadata",
            content_scope="calendar.details",
            syntax="Words plus after:YYYY-MM-DD, before:YYYY-MM-DD, with:<attendee name or email>, e.g. 'dentist after:2026-11-01 before:2026-12-01'. All terms must match.",
        ),
        Source(
            id="drive",
            label="Google Drive",
            item="file",
            items="files",
            whole="all your files",
            wants="look at your files",
            metadata_scope="drive.metadata",
            content_scope="drive.content",
            syntax="Words (searched in file text) plus name:<text>, type:doc|sheet|slides|pdf|folder|image, owner:<email>, after:/before:YYYY-MM-DD (last modified), e.g. 'type:sheet name:budget after:2026-01-01'. All terms must match.",
        ),
        Source(
            id="slack",
            label="Slack",
            item="message",
            items="messages",
            whole="all your Slack messages",
            wants="read your Slack",
            metadata_scope="slack.metadata",
            content_scope="slack.content",
            syntax="Slack search syntax: words plus in:#channel, from:@person, after:/before:YYYY-MM-DD, e.g. 'in:#launch from:@maya deadline'.",
        ),
    ]
}

ALL_SCOPES = set().union(*(s.scopes for s in SOURCES.values()))

CONNECTOR_PREFIX = "connector:"
_connectors: dict[str, Source] = {}


def custom_source(source_id: str, name: str, tools: frozenset[str] = frozenset(), ask_tools: frozenset[str] = frozenset()) -> Source:
    src = Source(
        id=source_id,
        label=name,
        item="result",
        items="results",
        whole=f"anything in {name}",
        wants=f"use {name}",
        metadata_scope="",
        content_scope="",
        syntax="",
        custom=True,
        tools=tools,
        ask_tools=ask_tools,
    )
    _connectors[source_id] = src
    return src


def source(source_id: str | None) -> Source:
    if source_id and source_id.startswith(CONNECTOR_PREFIX):
        # Named once the connector has been loaded in this process; a plain name until then.
        return _connectors.get(source_id) or Source(source_id, "your connector", "result", "results", "anything in it", "use your connector", "", "", "", custom=True)
    return SOURCES[source_id or "gmail"]
