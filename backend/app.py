"""ASGI entry point: `uvicorn app:app`."""

from nonce.main import app

__all__ = ["app"]
