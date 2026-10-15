from logging.config import fileConfig

from sqlalchemy import pool, text

from alembic import context

from app.config import settings
from app.db import Base, make_engine
from app import models  # noqa: F401  (registers models on Base.metadata)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL carries no credentials (PGUSER and PGPASSWORD do, app.config); `%` is escaped for the ini parser.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
# Every table, sequence and the version table live in the configured schema (DB_SCHEMA): the connection's
# search_path puts the migrations' unqualified names there, and alembic_version goes there too.
SCHEMA = settings.db_schema

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = make_engine(settings.database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # The schema exists already, or is created: that needs CREATE on the database, nothing more.
        if connection.execute(text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": SCHEMA}).first() is None:
            connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        # Always ends the transaction the check began: Alembic runs the migrations in its own, and inside an open
        # one it would commit nothing.
        connection.commit()
        context.configure(
            connection=connection, target_metadata=target_metadata, version_table_schema=SCHEMA
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
