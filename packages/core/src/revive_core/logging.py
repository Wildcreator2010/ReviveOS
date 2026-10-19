"""JSON logging helpers with shared secret redaction patterns."""

from __future__ import annotations

import json
import re

REDACTION_PATTERNS = (
    re.compile(r"\b(?:sk|ghp)_[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
)


def redact(value: str) -> str:
    value = REDACTION_PATTERNS[0].sub("[REDACTED]", value)
    value = REDACTION_PATTERNS[1].sub("Bearer [REDACTED]", value)
    return REDACTION_PATTERNS[2].sub(r"[REDACTED]@\1", value)


def json_log(event: str, **fields: object) -> str:
    return json.dumps({"event": event, **{k: redact(str(v)) for k, v in fields.items()}}, separators=(",", ":"))
