from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from revive_api.db.repository import ControlPlaneRepository


class FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.statement: Any = None

    async def scalars(self, statement: Any) -> FakeScalars:
        self.statement = statement
        return FakeScalars(self.rows)

    async def get(self, model: Any, key: str) -> Any:
        return self.rows[0] if self.rows and self.rows[0].id == key else None


@pytest.mark.asyncio
async def test_list_api_keys_filters_by_user_and_maps_revocation_fields() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    revoked = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            id="key_1",
            user_id="user_1",
            prefix="rv_a",
            key_hash="hash_a",
            label="first",
            created_at=created,
            revoked_at=None,
        ),
        SimpleNamespace(
            id="key_2",
            user_id="user_1",
            prefix="rv_b",
            key_hash="hash_b",
            label="second",
            created_at=created,
            revoked_at=revoked,
        ),
    ]
    session = FakeSession(rows)

    result = await ControlPlaneRepository(session).list_api_keys("user_1")

    assert [key.id for key in result] == ["key_1", "key_2"]
    assert result[0].label == "first"
    assert result[0].revoked_at is None
    assert result[1].revoked_at == revoked
    where_clause = session.statement.whereclause
    assert "api_keys.user_id" in str(where_clause)
    assert "user_1" in str(where_clause.compile().params.values())


@pytest.mark.asyncio
async def test_get_user_by_id_preserves_get_user_contract() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    row = SimpleNamespace(
        id="user_1",
        email="user@example.com",
        password_hash="hash",
        role="admin",
        created_at=created,
    )
    repository = ControlPlaneRepository(FakeSession([row]))

    user = await repository.get_user_by_id("user_1")

    assert user is not None
    assert (user.id, user.email, user.role) == ("user_1", "user@example.com", "admin")
    assert user.created_at == created
