"""Alembic environment for the backend.

Two things here are specific to this stack and worth reading before changing:

1. The database URL comes from `src/config.py`, not from alembic.ini, so
   connection settings have one source of truth and no credentials are tracked.

2. **The backend shares its database with the game-server**, which owns
   `servers`, `tasks` and `server_player_counts`. Those tables are absent from
   this metadata, so without a filter autogenerate would cheerfully propose
   dropping them. `include_object` restricts Alembic to tables the backend
   actually declares.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config import Config
from src.database import Base

# Importing the package registers every model on Base.metadata.
import src.models  # noqa: F401

config = context.config
# The app's configuration is the default, but an explicitly supplied URL wins -
# otherwise the migration chain can only ever be run against the real database,
# which makes it impossible to test on an empty one before shipping it.
if not config.get_main_option('sqlalchemy.url', None):
    config.set_main_option('sqlalchemy.url', Config.SQLALCHEMY_DATABASE_URI)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """Ignore anything the backend does not own.

    Without this, a table the game-server created looks to Alembic like a table
    that should no longer exist.
    """
    if type_ == 'table':
        return name in target_metadata.tables
    return True


def run_migrations_offline():
    """Emit SQL to stdout instead of running it."""
    context.configure(
        url=config.get_main_option('sqlalchemy.url'),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        compare_type=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
