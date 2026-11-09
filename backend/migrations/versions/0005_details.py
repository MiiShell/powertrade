"""details: monthly bars view, instrument profile (cleaned provider data), technical snapshots

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW price_bar_1mo AS
        SELECT instrument_id,
               time_bucket(INTERVAL '1 month', ts) AS ts,
               first(open, ts)  AS open,
               max(high)        AS high,
               min(low)         AS low,
               last(close, ts)  AS close,
               last(adj_close, ts) AS adj_close,
               sum(volume)      AS volume
        FROM price_bar_1d
        GROUP BY instrument_id, 2
    """)
    op.execute("""
        CREATE TABLE instrument_profile (
            instrument_id   bigint PRIMARY KEY REFERENCES instrument(id) ON DELETE CASCADE,
            source          text NOT NULL,
            company_name    text,
            description     text CHECK (length(description) <= 6000),
            sector          text,
            industry        text,
            country         char(2),
            exchange        text,
            currency        char(3),
            website         text CHECK (website ~ '^https?://'),
            ceo             text,
            employees       integer CHECK (employees >= 0),
            ipo_date        date,
            isin            char(12),
            cusip           text,
            market_cap      double precision CHECK (market_cap >= 0),
            beta            double precision,
            last_dividend   double precision,
            avg_volume      double precision,
            is_etf          boolean,
            fetched_at      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE technical_snapshot (
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            tf              text NOT NULL CHECK (tf IN ('1d','1w','1mo')),
            ts              timestamptz NOT NULL,
            summary_label   text NOT NULL,
            summary_score   double precision,
            oscillators_label text NOT NULL,
            ma_label        text NOT NULL,
            counts          jsonb NOT NULL,
            rows            jsonb NOT NULL,
            computed_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (instrument_id, tf, ts)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS technical_snapshot")
    op.execute("DROP TABLE IF EXISTS instrument_profile")
    op.execute("DROP VIEW IF EXISTS price_bar_1mo")
