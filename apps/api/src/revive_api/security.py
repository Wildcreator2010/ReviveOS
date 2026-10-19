"""Authentication helpers for JWT and API keys."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher

_passwords = PasswordHasher()


def hash_password(value: str) -> str:
    return _passwords.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return _passwords.verify(hashed, value)
    except Exception:
        return False


def issue_token(
    subject: str,
    secret: str,
    *,
    kind: str = "access",
    expires: timedelta | None = None,
    family: str | None = None,
) -> str:
    lifetime = expires or (timedelta(minutes=15) if kind == "access" else timedelta(days=7))
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": subject,
        "type": kind,
        "jti": secrets.token_urlsafe(18),
        "iat": now,
        "exp": now + lifetime,
    }
    if family:
        claims["family"] = family
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(token: str, secret: str, *, kind: str = "access") -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload if payload.get("type") == kind and isinstance(payload.get("sub"), str) else None
    except jwt.PyJWTError:
        return None


def new_api_key() -> tuple[str, str, str]:
    value = "rvk_" + secrets.token_urlsafe(32)
    return value, value[:8], hash_password(value)


def verify_api_key(value: str, hashed: str) -> bool:
    return verify_password(value, hashed)
