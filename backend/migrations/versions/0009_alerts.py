"""alerts: rules + event history

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

KINDS = (
    "('price_above','price_below','change_pct','ma_cross_above','ma_cross_below',"
    "'rsi_above','rsi_below','fv_upside_above')"
)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE alert (
            id                  bigserial PRIMARY KEY,
            instrument_id       bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            kind                text NOT NULL CHECK (kind IN {KINDS}),
            params              jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(params) = 'object'),
            note                text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
            cooldown_minutes    integer NOT NULL DEFAULT 1440 CHECK (cooldown_minutes BETWEEN 0 AND 43200),
            notify_telegram     boolean NOT NULL DEFAULT true,
            is_active           boolean NOT NULL DEFAULT true,
            last_state          boolean,
            last_value          double precision,
            last_evaluated_at   timestamptz,
            last_triggered_at   timestamptz,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX alert_instrument_idx ON alert (instrument_id) WHERE is_active")
    op.execute("""
        CREATE TABLE alert_event (
            id              bigserial PRIMARY KEY,
            alert_id        bigint REFERENCES alert(id) ON DELETE SET NULL,
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            kind            text NOT NULL,
            triggered_at    timestamptz NOT NULL DEFAULT now(),
            value           double precision,
            message         text NOT NULL,
            delivery        text NOT NULL CHECK (delivery IN ('pending','sent','failed','skipped')),
            delivery_error  text,
            read_at         timestamptz
        )
    """)
    op.execute("CREATE INDEX alert_event_time_idx ON alert_event (triggered_at DESC)")
    op.execute("CREATE INDEX alert_event_alert_idx ON alert_event (alert_id)")
    op.execute("CREATE INDEX alert_event_instrument_idx ON alert_event (instrument_id)")
    op.execute("CREATE INDEX alert_event_unread_idx ON alert_event (triggered_at) WHERE read_at IS NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_event")
    op.execute("DROP TABLE IF EXISTS alert")
