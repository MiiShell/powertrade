"""fundamentals (annual facts), score snapshots, ranking strategy

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

METRICS = (
    "('revenue','net_income','operating_income','eps_diluted','shares_diluted','operating_cf','capex',"
    "'free_cf','dps','debt','cash','equity','assets')"
)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE fundamental_fact (
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            metric          text NOT NULL CHECK (metric IN {METRICS}),
            fiscal_year     smallint NOT NULL CHECK (fiscal_year BETWEEN 1950 AND 2200),
            period_end      date NOT NULL,
            value           double precision NOT NULL,
            unit            text NOT NULL,
            source          text NOT NULL CHECK (source IN ('sec','fmp','fixture')),
            filed           date,
            fetched_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (instrument_id, metric, fiscal_year)
        )
    """)
    op.execute("""
        CREATE TABLE corporate_action (
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            ex_date         date NOT NULL,
            kind            text NOT NULL CHECK (kind IN ('split')),
            ratio           double precision NOT NULL CHECK (ratio > 0),
            source          text NOT NULL,
            PRIMARY KEY (instrument_id, ex_date, kind)
        )
    """)
    op.execute("""
        CREATE TABLE fundamentals_run (
            instrument_id   bigint PRIMARY KEY REFERENCES instrument(id) ON DELETE CASCADE,
            source          text,
            status          text NOT NULL,
            facts           integer NOT NULL DEFAULT 0,
            error           text,
            finished_at     timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE score_snapshot (
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            as_of           date NOT NULL,
            dividend_yield_score  smallint,
            dividend_growth_score smallint,
            earnings_growth_score smallint,
            ranking_points  smallint,
            detail          jsonb NOT NULL,
            computed_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (instrument_id, as_of)
        )
    """)
    op.execute("""
        CREATE TABLE ranking_strategy (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name        text NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 60),
            targets     jsonb NOT NULL,
            weights     jsonb NOT NULL,
            is_default  boolean NOT NULL DEFAULT false,
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        INSERT INTO ranking_strategy (name, targets, weights, is_default) VALUES (
          'Standard',
          '{"earnings_stability": 0.9, "earnings_growth_5y": 10, "dividend_yield": 2.0, "dividend_growth_5y": 8,
            "dividend_stability": 0.9, "max_payback_years": 4, "min_discount": 6}',
          '{"earnings_stability": 1, "earnings_growth_5y": 1, "dividend_yield": 1, "dividend_growth_5y": 1,
            "dividend_stability": 1, "max_payback_years": 1, "min_discount": 1}',
          true)
    """)


def downgrade() -> None:
    for t in (
        "ranking_strategy",
        "score_snapshot",
        "fundamentals_run",
        "corporate_action",
        "fundamental_fact",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t}")
