"""Text messages through Twilio, following BeforePay's lib/phone.ts.

Twilio Verify sends and checks the code that proves a user owns their number. Approval
requests go out through the Messaging API, which needs TWILIO_FROM_NUMBER or
TWILIO_MESSAGING_SERVICE_SID. Without Twilio, outside production, codes and messages are
printed to the server log so the flow can be tried locally; in production texting is off.
"""

import logging
import re
import secrets
from typing import Literal

import httpx

from .config import settings
from .crypto import hash_token

log = logging.getLogger(__name__)

Mode = Literal["sms", "dev", "off"]

# Dev-mode codes, hashed. Only used locally, where there is one process.
_dev_codes: dict[str, str] = {}


def _account() -> tuple[str, str] | None:
    s = settings()
    return (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid and s.twilio_auth_token else None


def _fallback() -> Mode:
    return "off" if settings().production else "dev"


def enabled() -> bool:
    return settings().sms_enabled


def verify_mode() -> Mode:
    if not enabled():
        return "off"
    return "sms" if _account() and settings().twilio_verify_service_sid else _fallback()


def message_mode() -> Mode:
    if not enabled():
        return "off"
    s = settings()
    return "sms" if _account() and (s.twilio_from_number or s.twilio_messaging_service_sid) else _fallback()


def normalize_phone(raw: str) -> str | None:
    """E.164 from what people type. Ten digits are taken as a US number."""
    trimmed = raw.strip()
    digits = re.sub(r"\D", "", trimmed)
    if trimmed.startswith("+"):
        e164 = f"+{digits}"
    elif len(digits) == 10:
        e164 = f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        e164 = f"+{digits}"
    else:
        return None
    return e164 if re.fullmatch(r"\+[1-9]\d{7,14}", e164) else None


async def _twilio(url: str, data: dict[str, str]) -> tuple[int, dict]:
    account = _account()
    assert account
    async with httpx.AsyncClient(timeout=10, auth=account) as client:
        res = await client.post(url, data=data)
    try:
        body = res.json()
    except ValueError:
        body = {}
    return res.status_code, body


def _verify_url(path: str) -> str:
    return f"https://verify.twilio.com/v2/Services/{settings().twilio_verify_service_sid}/{path}"


async def send_code(phone: str) -> str | None:
    """Returns an error message for the user, or None when the code is on its way."""
    mode = verify_mode()
    if mode == "off":
        return "Texting isn't available right now."
    if mode == "dev":
        code = f"{secrets.randbelow(1_000_000):06d}"
        _dev_codes[phone] = hash_token(code)
        log.warning("[nonce] Code for %s: %s  (dev mode: set TWILIO_* to send real texts)", phone, code)
        return None
    status, body = await _twilio(_verify_url("Verifications"), {"To": phone, "Channel": "sms"})
    if status < 300:
        return None
    log.error("Twilio Verify send failed: %s %s", status, body.get("message"))
    if status == 400:
        return "That number can't receive texts. Check it and try again."
    if status == 403:
        return "nonce can't text this number yet. We're finishing setup with our text provider."
    return "Couldn't send the code. Try again in a moment."


async def check_code(phone: str, code: str) -> bool:
    if not re.fullmatch(r"\d{4,10}", code):
        return False
    mode = verify_mode()
    if mode == "dev":
        expected = _dev_codes.get(phone)
        ok = expected is not None and secrets.compare_digest(expected, hash_token(code))
        if ok:
            _dev_codes.pop(phone, None)
        return ok
    if mode == "off":
        return False
    status, body = await _twilio(_verify_url("VerificationCheck"), {"To": phone, "Code": code})
    return status < 300 and body.get("status") == "approved"


async def send_text(phone: str, body: str) -> bool:
    mode = message_mode()
    if mode == "off":
        return False
    if mode == "dev":
        log.warning("[nonce] Text to %s:\n%s", phone, body)
        return True
    s = settings()
    sender = {"MessagingServiceSid": s.twilio_messaging_service_sid} if s.twilio_messaging_service_sid else {"From": s.twilio_from_number or ""}
    status, res = await _twilio(
        f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
        {"To": phone, "Body": body, **sender},
    )
    if status >= 300:
        log.error("Twilio message failed: %s %s", status, res.get("message"))
    return status < 300
