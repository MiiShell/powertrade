"""Claude stock reports (versioned per instrument)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE report (
            id              bigserial PRIMARY KEY,
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            version         integer NOT NULL CHECK (version > 0),
            model           text NOT NULL,
            status          text NOT NULL CHECK (status IN ('queued','running','done','refused','failed')),
            reserved_usd    numeric(10,6) NOT NULL DEFAULT 0,
            snapshot        jsonb NOT NULL,
            sections        jsonb,
            charts          jsonb,
            sources         jsonb,
            warnings        jsonb,
            stats           jsonb,
            error           text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            finished_at     timestamptz,
            UNIQUE (instrument_id, version)
        )
    """)
    op.execute("CREATE INDEX report_instrument_idx ON report (instrument_id, version DESC)")
    op.execute("CREATE INDEX report_open_idx ON report (status) WHERE status IN ('queued','running')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report")
