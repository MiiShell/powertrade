"""allow provider 'fmp'; add FMP as fallback source for seeded stocks

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE instrument_source DROP CONSTRAINT instrument_source_provider_check")
    op.execute(
        "ALTER TABLE instrument_source ADD CONSTRAINT instrument_source_provider_check "
        "CHECK (provider IN ('yahoo','stooq','kraken','fmp'))"
    )
    # Yahoo stays primary (no quota); FMP before Stooq as fallback for stocks/ETFs.
    op.execute("""
        INSERT INTO instrument_source (instrument_id, provider, provider_symbol, priority)
        SELECT id, 'fmp', symbol, 2 FROM instrument WHERE type IN ('stock', 'etf')
        ON CONFLICT DO NOTHING
    """)
    op.execute("UPDATE instrument_source SET priority = 3 WHERE provider = 'stooq'")


def downgrade() -> None:
    op.execute("DELETE FROM instrument_source WHERE provider = 'fmp'")
    op.execute("UPDATE instrument_source SET priority = 2 WHERE provider = 'stooq'")
    op.execute("ALTER TABLE instrument_source DROP CONSTRAINT instrument_source_provider_check")
    op.execute(
        "ALTER TABLE instrument_source ADD CONSTRAINT instrument_source_provider_check "
        "CHECK (provider IN ('yahoo','stooq','kraken'))"
    )
