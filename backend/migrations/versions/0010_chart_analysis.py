"""Claude chart analysis + AI call log (cost tracking / budget)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE chart_analysis (
            id              bigserial PRIMARY KEY,
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            tf              text NOT NULL CHECK (tf IN ('1d','1w')),
            model           text NOT NULL,
            effort          text NOT NULL,
            status          text NOT NULL CHECK (status IN ('queued','running','done','refused','failed')),
            reserved_usd    numeric(10,6) NOT NULL DEFAULT 0,
            context         jsonb NOT NULL,
            result          jsonb,
            error           text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            finished_at     timestamptz
        )
    """)
    op.execute(
        "CREATE INDEX chart_analysis_instrument_idx ON chart_analysis (instrument_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX chart_analysis_open_idx ON chart_analysis (status) WHERE status IN ('queued','running')"
    )
    op.execute("""
        CREATE TABLE ai_call_log (
            id                  bigserial PRIMARY KEY,
            feature             text NOT NULL CHECK (feature IN ('chart_analysis','report')),
            ref_id              bigint,
            model_requested     text NOT NULL,
            model_served        text,
            status              text NOT NULL CHECK (status IN ('ok','refused','error')),
            input_tokens        integer NOT NULL DEFAULT 0,
            output_tokens       integer NOT NULL DEFAULT 0,
            cache_read_tokens   integer NOT NULL DEFAULT 0,
            cache_write_tokens  integer NOT NULL DEFAULT 0,
            cost_usd            numeric(10,6) NOT NULL DEFAULT 0,
            request_id          text,
            error               text,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ai_call_log_time_idx ON ai_call_log (created_at DESC)")
    op.execute("CREATE INDEX ai_call_log_ref_idx ON ai_call_log (feature, ref_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_call_log")
    op.execute("DROP TABLE IF EXISTS chart_analysis")
