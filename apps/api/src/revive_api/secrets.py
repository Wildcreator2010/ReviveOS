"""Small authenticated encryption for admin-managed provider keys.

The deployment already has a high-entropy JWT secret; derive a domain-separated
HMAC-SHA256 key from it and use HMAC-CTR as a stream cipher plus an HMAC tag.
This avoids a new dependency while never storing the provider key in plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

_CONTEXT = b"revive/llm-settings/v1"
_NONCE_BYTES = 16
_TAG_BYTES = 32


def _master() -> bytes:
    raw = (
        os.getenv("REVIVE_SECRETS__KEY", "").strip()
        or os.getenv("REVIVE_JWT__SECRET", "").strip()
        or "dev-only-change-me"
    )
    return hmac.new(raw.encode("utf-8"), _CONTEXT, hashlib.sha256).digest()


def _stream(master: bytes, nonce: bytes, length: int) -> bytes:
    blocks = bytearray()
    counter = 0
    while len(blocks) < length:
        blocks.extend(hmac.new(master, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(blocks[:length])


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    nonce = secrets.token_bytes(_NONCE_BYTES)
    payload = value.encode("utf-8")
    stream = _stream(_master(), nonce, len(payload))
    encrypted = bytes(left ^ right for left, right in zip(payload, stream, strict=True))
    tag = hmac.new(_master(), b"tag" + nonce + encrypted, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + encrypted).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    if len(raw) < _NONCE_BYTES + _TAG_BYTES:
        raise ValueError("encrypted secret is truncated")
    nonce = raw[:_NONCE_BYTES]
    tag = raw[_NONCE_BYTES : _NONCE_BYTES + _TAG_BYTES]
    encrypted = raw[_NONCE_BYTES + _TAG_BYTES :]
    expected = hmac.new(_master(), b"tag" + nonce + encrypted, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("encrypted secret failed authentication")
    stream = _stream(_master(), nonce, len(encrypted))
    return bytes(left ^ right for left, right in zip(encrypted, stream, strict=True)).decode("utf-8")


__all__ = ["decrypt_secret", "encrypt_secret"]
