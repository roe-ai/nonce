"""Web Push: alerts to the dashboard installed on a phone, or any browser that turned notifications on.

Payloads are encrypted for each browser (RFC 8291), so Apple's and Google's push services
carry them without reading them. Subscriptions the push service reports gone are dropped.

Generate the server's keys once with `uv run python -m privato.webpush` and set them as
VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY.
"""

import asyncio
import base64
import json
import logging

from . import db
from .config import settings

log = logging.getLogger(__name__)

GONE = {404, 410}


def configured() -> bool:
    s = settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_keys() -> tuple[str, str]:
    """(public, private), both base64url: the uncompressed P-256 point and the raw private scalar."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(public), _b64(key.private_numbers().private_value.to_bytes(32, "big"))


def _subject() -> str:
    s = settings()
    if s.vapid_subject:
        return s.vapid_subject
    return s.dashboard_url if s.dashboard_url.startswith("https://") else "mailto:privato@localhost"


async def subscribe(user_id: str, endpoint: str, p256dh: str, auth: str, device: str | None) -> None:
    await db.q("DELETE FROM push_subscriptions WHERE endpoint = ?", endpoint)
    await db.insert(
        "push_subscriptions",
        {"user_id": user_id, "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "device": device, "created_at": db.now()},
    )


async def unsubscribe(user_id: str, endpoint: str) -> None:
    await db.q("DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", user_id, endpoint)


def _deliver(sub: dict, data: str, urgent: bool) -> int | None:
    """None when delivered, else the push service's status."""
    from pywebpush import WebPushException, webpush

    s = settings()
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=data,
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": _subject()},
            ttl=3600,
            headers={"Urgency": "high" if urgent else "normal"},
            timeout=5,
        )
        return None
    except WebPushException as e:
        return e.response.status_code if e.response is not None else 0


async def send(user_id: str, *, title: str, body: str, url: str, tag: str | None = None, urgent: bool = False) -> int:
    """Push to every browser the user turned notifications on in. Returns how many got it."""
    if not configured():
        return 0
    subs = await db.q("SELECT * FROM push_subscriptions WHERE user_id = ?", user_id)
    data = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    results = await asyncio.gather(*(asyncio.to_thread(_deliver, sub, data, urgent) for sub in subs), return_exceptions=True)
    delivered = 0
    for sub, result in zip(subs, results, strict=True):
        if result is None:
            delivered += 1
        elif result in GONE:
            await db.q("DELETE FROM push_subscriptions WHERE id = ?", sub["id"])
        else:
            log.warning("web push failed (%s) for %s", result, sub["endpoint"][:60])
    return delivered


if __name__ == "__main__":
    public, private = generate_keys()
    print(f"VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}")
