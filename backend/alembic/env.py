"""Alembic environment.

The database URL comes from `app.config.settings`, not `alembic.ini`, so there
is exactly one source of truth for configuration and no credentials in a
tracked file.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.config import settings
from app.database.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Return the connection URL with an explicit psycopg (v3) driver.

    SQLAlchemy resolves a bare `postgresql://` to psycopg2, which this project
    does not install. Normalizing here keeps `.env` a plain Postgres URL that
    the Supabase dashboard can hand you verbatim.
    """
    url = str(settings.database_url)
    scheme, separator, rest = url.partition("://")
    if "+" in scheme:
        return url
    return f"{scheme}+psycopg{separator}{rest}"


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep Supabase-owned schemas out of autogenerate.

    `auth.users` is present in the metadata only so `public.users` can declare
    a foreign key to it. Without this filter, autogenerate would propose
    creating a table Supabase already owns.
    """
    schema = getattr(obj, "schema", None)
    return not (type_ == "table" and schema in {"auth", "storage", "extensions"})


def run_migrations_offline() -> None:
    """Render migrations as SQL without connecting to a database."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
