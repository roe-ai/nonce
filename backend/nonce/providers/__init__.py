from .base import Provider


def provider_for(connection: dict) -> Provider:
    from .calendar import GoogleCalendar
    from .drive import GoogleDrive
    from .gmail import GoogleGmail
    from .slack import Slack

    cls = {"gmail": GoogleGmail, "calendar": GoogleCalendar, "drive": GoogleDrive, "slack": Slack}[connection["provider"]]
    return cls(connection["credentials_enc"])


def check_filter(source: str, q: str) -> None:
    """Raises AccessError(bad_query) for filters this source can't apply. Gmail parses its own."""
    from . import calendar, drive, slack

    checker = {"calendar": calendar.check_filter, "drive": drive.check_filter, "slack": slack.check_filter}.get(source)
    if checker:
        checker(q)
