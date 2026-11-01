import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from .config import settings


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def encrypt(plaintext: str) -> str:
    return Fernet(settings().nonce_encryption_key.encode()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return Fernet(settings().nonce_encryption_key.encode()).decrypt(ciphertext.encode()).decode()


def sign(*parts: str) -> str:
    msg = "|".join(parts).encode()
    return hmac.new(settings().nonce_admin_token.encode(), msg, hashlib.sha256).hexdigest()[:32]


def verify(sig: str, *parts: str) -> bool:
    return hmac.compare_digest(sig, sign(*parts))
