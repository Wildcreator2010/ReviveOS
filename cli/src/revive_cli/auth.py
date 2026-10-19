"""CLI credential handling (T-CLI-01).

Tokens are stored in the OS keyring when available.  When it is not, we fall
back to ~/.revive/credentials.json with mode 0600 and warn loudly.  A token is
never written to shell history, a config file in the repo, or an environment
variable we create.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KEYRING_SERVICE = "reviveos"
KEYRING_USER = "cli"


def credentials_path() -> Path:
    override = os.environ.get("REVIVE_CREDENTIALS_FILE")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~")) / ".revive" / "credentials.json"


@dataclass
class Credentials:
    access_token: str = ""
    refresh_token: str = ""
    server: str = ""
    api_key: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "server": self.server,
        }
        if self.api_key:
            payload["api_key"] = self.api_key
        payload.update(self.extra)
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Credentials:
        known = {"access_token", "refresh_token", "server", "api_key"}
        return cls(
            access_token=str(value.get("access_token", "")),
            refresh_token=str(value.get("refresh_token", "")),
            server=str(value.get("server", "")),
            api_key=str(value.get("api_key", "")),
            extra={key: item for key, item in value.items() if key not in known},
        )


class CredentialStore:
    """Keyring first, 0600 JSON file second."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or credentials_path()
        self.used_fallback = False

    def _keyring(self) -> Any | None:
        try:
            import keyring  # noqa: PLC0415 - optional dependency

            return keyring
        except Exception:
            return None

    def save(self, credentials: Credentials) -> str:
        keyring = self._keyring()
        if keyring is not None:
            try:
                keyring.set_password(KEYRING_SERVICE, KEYRING_USER, json.dumps(credentials.to_dict()))
                return "keyring"
            except Exception:
                pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(credentials.to_dict(), indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - platform specific
            pass
        self.used_fallback = True
        return str(self.path)

    def load(self) -> Credentials:
        keyring = self._keyring()
        if keyring is not None:
            try:
                raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
                if raw:
                    return Credentials.from_dict(json.loads(raw))
            except Exception:
                pass
        if self.path.is_file():
            try:
                return Credentials.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return Credentials()
        return Credentials()

    def clear(self) -> None:
        keyring = self._keyring()
        if keyring is not None:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:
                pass
        if self.path.is_file():
            self.path.unlink()


__all__ = [
    "KEYRING_SERVICE",
    "KEYRING_USER",
    "CredentialStore",
    "Credentials",
    "credentials_path",
]
