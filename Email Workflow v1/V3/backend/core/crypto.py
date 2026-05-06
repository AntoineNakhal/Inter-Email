"""Small crypto helpers for token storage and hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet


def hash_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def encrypt_text(value: str, secret: str) -> str:
    key = _derive_key(secret)
    payload = str(value or "").encode("utf-8")
    return Fernet(key).encrypt(payload).decode("ascii")


def decrypt_text(value: str, secret: str) -> str:
    key = _derive_key(secret)
    plain = Fernet(key).decrypt(str(value or "").encode("ascii"))
    return plain.decode("utf-8")


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left or ""), str(right or ""))


def _derive_key(secret: str) -> bytes:
    normalized = str(secret or "").strip()
    if not normalized:
        raise ValueError("AUTH_TOKEN_ENCRYPTION_KEY is required.")
    try:
        decoded = base64.urlsafe_b64decode(normalized.encode("ascii"))
        if len(decoded) == 32:
            return normalized.encode("ascii")
    except Exception:
        pass
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)
