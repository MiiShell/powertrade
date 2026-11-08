from alembic import context
from sqlalchemy import create_engine, pool

from app.settings import get_settings

# Migrations run as the DB owner role; the app connects with a DML-only role.
url = get_settings().owner_db_url


def run() -> None:
    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn)
        with context.begin_transaction():
            context.run_migrations()


run()
