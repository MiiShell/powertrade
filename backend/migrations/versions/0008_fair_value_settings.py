"""fair value settings per stock (period, user-overridden average multiples)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE fair_value_setting (
            instrument_id   bigint PRIMARY KEY REFERENCES instrument(id) ON DELETE CASCADE,
            period          text NOT NULL DEFAULT '10' CHECK (period IN ('5','8','10','15','20','all')),
            overrides       jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(overrides) = 'object'),
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fair_value_setting")
