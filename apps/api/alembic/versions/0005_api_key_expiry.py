"""add api key expiry"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_api_key_expiry"
down_revision = "0004_runtime_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "expires_at")
