"""chart levels (horizontal support/resistance lines)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE chart_level (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            price           double precision NOT NULL CHECK (price > 0),
            color           text NOT NULL DEFAULT '#3fb950' CHECK (color ~ '^#[0-9a-fA-F]{6}$'),
            label           text NOT NULL DEFAULT '' CHECK (length(label) <= 40),
            created_at      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX chart_level_instrument_idx ON chart_level (instrument_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chart_level")
