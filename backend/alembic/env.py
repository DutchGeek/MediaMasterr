from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# alembic Config object (gives access to alembic.ini values)
config = context.config

# set up python logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# import all models so their tables are registered on Base.metadata before
# autogenerate compares the schema.
import backend.database.models as _models
from backend.core.settings import settings
from backend.database import Base

target_metadata = Base.metadata

# synchronous SQLite URL used for CLI autogenerate and offline mode.
_DB_URL = f"sqlite:///{settings.db_path}"


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required)."""
    context.configure(
        url=_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    When called from the app lifespan (via conn.run_sync), an open connection
    is injected via config.attributes["connection"] so Alembic reuses it
    instead of opening a separate conflicting connection.

    When called from the Alembic CLI (autogenerate, etc.), no connection is
    pre injected and a fresh sync engine is created instead.
    """
    injected = config.attributes.get("connection", None)
    # app startup path (reuse the already open connection)
    if injected is not None:
        do_run_migrations(injected)

    # CLI path (alembic revision --autogenerate, etc)
    else:
        connectable = create_engine(_DB_URL, poolclass=pool.NullPool)
        with connectable.connect() as connection:
            do_run_migrations(connection)
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
