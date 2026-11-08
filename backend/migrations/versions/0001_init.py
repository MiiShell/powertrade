"""init: timescaledb + system_check hypertable

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.create_table(
        "system_check",
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("nonce", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("ts", "nonce"),
    )
    op.execute("SELECT create_hypertable('system_check', by_range('ts', INTERVAL '1 day'))")
    op.execute("SELECT add_retention_policy('system_check', INTERVAL '7 days')")


def downgrade() -> None:
    op.drop_table("system_check")
