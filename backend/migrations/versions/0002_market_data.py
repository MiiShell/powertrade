"""market data: instruments, sources, watchlists, daily bars (hypertable), weekly view, ingestion runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INSTRUMENT_TYPES = "('stock','etf','index','crypto','commodity','fx')"

SEED = [
    # symbol, name, type, currency, [(provider, provider_symbol, priority)]
    ("NVDA", "NVIDIA", "stock", "USD", [("yahoo", "NVDA", 1), ("stooq", "nvda.us", 2)]),
    ("BTC", "Bitcoin", "crypto", "USD", [("yahoo", "BTC-USD", 1), ("kraken", "XBTUSD", 2)]),
    ("ETH", "Ethereum", "crypto", "USD", [("yahoo", "ETH-USD", 1), ("kraken", "ETHUSD", 2)]),
    ("SOL", "Solana", "crypto", "USD", [("yahoo", "SOL-USD", 1), ("kraken", "SOLUSD", 2)]),
    ("XMR", "Monero", "crypto", "USD", [("yahoo", "XMR-USD", 1), ("kraken", "XMRUSD", 2)]),
    ("GOLD", "Gold (Futures)", "commodity", "USD", [("yahoo", "GC=F", 1)]),
    ("SILVER", "Silber (Futures)", "commodity", "USD", [("yahoo", "SI=F", 1)]),
]


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE instrument (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            symbol      text NOT NULL CHECK (symbol ~ '^[A-Z0-9.\\-=^_]{{1,32}}$'),
            name        text NOT NULL DEFAULT '',
            type        text NOT NULL CHECK (type IN {INSTRUMENT_TYPES}),
            currency    char(3) NOT NULL CHECK (currency ~ '^[A-Z]{{3}}$'),
            isin        char(12) UNIQUE,
            exchange    text,
            country     char(2),
            is_active   boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (symbol, type)
        )
    """)
    op.execute("""
        CREATE TABLE instrument_source (
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            provider        text NOT NULL CHECK (provider IN ('yahoo','stooq','kraken')),
            provider_symbol text NOT NULL,
            priority        smallint NOT NULL DEFAULT 1,
            PRIMARY KEY (instrument_id, provider)
        )
    """)
    op.execute("""
        CREATE TABLE watchlist (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name        text NOT NULL UNIQUE,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE watchlist_item (
            watchlist_id    bigint NOT NULL REFERENCES watchlist(id) ON DELETE CASCADE,
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            position        integer NOT NULL DEFAULT 0,
            added_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (watchlist_id, instrument_id)
        )
    """)
    op.execute("CREATE INDEX watchlist_item_instrument_idx ON watchlist_item (instrument_id)")

    op.execute("""
        CREATE TABLE price_bar_1d (
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            ts              timestamptz NOT NULL,
            open            double precision NOT NULL,
            high            double precision NOT NULL,
            low             double precision NOT NULL,
            close           double precision NOT NULL,
            adj_close       double precision,
            volume          double precision,
            source          text NOT NULL,
            fetched_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (instrument_id, ts),
            CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0 AND high >= low)
        )
    """)
    op.execute("SELECT create_hypertable('price_bar_1d', by_range('ts', INTERVAL '1 year'))")
    op.execute("""
        ALTER TABLE price_bar_1d SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'instrument_id',
            timescaledb.compress_orderby = 'ts DESC'
        )
    """)
    op.execute("SELECT add_compression_policy('price_bar_1d', INTERVAL '180 days')")

    # Weekly bars aggregated on the fly (weeks start Monday). Small data -> plain view;
    # can become a continuous aggregate later without API changes.
    op.execute("""
        CREATE VIEW price_bar_1w AS
        SELECT instrument_id,
               time_bucket(INTERVAL '7 days', ts, TIMESTAMPTZ '2000-01-03 00:00:00+00') AS ts,
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
        CREATE TABLE ingestion_run (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            instrument_id   bigint NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
            provider        text,
            started_at      timestamptz NOT NULL DEFAULT now(),
            finished_at     timestamptz,
            status          text NOT NULL CHECK (status IN ('running','success','failed')),
            rows            integer NOT NULL DEFAULT 0,
            error           text
        )
    """)
    op.execute("CREATE INDEX ingestion_run_instrument_idx ON ingestion_run (instrument_id, started_at DESC)")

    op.execute("INSERT INTO watchlist (name) VALUES ('Standard')")
    for pos, (symbol, name, typ, ccy, sources) in enumerate(SEED):
        op.execute(
            f"INSERT INTO instrument (symbol, name, type, currency) "
            f"VALUES ('{symbol}', '{name}', '{typ}', '{ccy}')"
        )
        for provider, psym, prio in sources:
            op.execute(
                f"INSERT INTO instrument_source (instrument_id, provider, provider_symbol, priority) "
                f"SELECT id, '{provider}', '{psym}', {prio} FROM instrument "
                f"WHERE symbol = '{symbol}' AND type = '{typ}'"
            )
        op.execute(
            f"INSERT INTO watchlist_item (watchlist_id, instrument_id, position) "
            f"SELECT w.id, i.id, {pos} FROM watchlist w, instrument i "
            f"WHERE w.name = 'Standard' AND i.symbol = '{symbol}' AND i.type = '{typ}'"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingestion_run")
    op.execute("DROP VIEW IF EXISTS price_bar_1w")
    op.execute("DROP TABLE IF EXISTS price_bar_1d")
    op.execute("DROP TABLE IF EXISTS watchlist_item")
    op.execute("DROP TABLE IF EXISTS watchlist")
    op.execute("DROP TABLE IF EXISTS instrument_source")
    op.execute("DROP TABLE IF EXISTS instrument")
