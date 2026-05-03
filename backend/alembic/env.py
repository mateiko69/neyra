import sys
from logging.config import fileConfig

from alembic import context
from alembic.ddl.impl import DefaultImpl
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, String, Table, engine_from_config, pool, text
from sqlalchemy.engine.url import make_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

try:
    from app.core.config import settings
except ValidationError as exc:
    sys.stderr.write("[alembic] Failed to load application settings.\n")
    for err in exc.errors():
        loc = err.get("loc") or ()
        if "DATABASE_URL" in loc:
            sys.stderr.write(f"[alembic] DATABASE_URL: {err.get('msg')}\n")
    sys.stderr.write(
        "[alembic] Set DATABASE_URL (name only referenced here — never logged) to your Railway PostgreSQL URL.\n"
    )
    raise SystemExit(1)

db_url = settings.DATABASE_URL
try:
    make_url(db_url)
except Exception:
    sys.stderr.write(
        "[alembic] DATABASE_URL could not be parsed as a SQLAlchemy URL. "
        "Fix the DATABASE_URL variable (secret value never printed).\n"
    )
    raise SystemExit(1)

config.set_main_option("sqlalchemy.url", db_url)

from app.db.base import Base  # noqa: E402 — load after DATABASE_URL is validated
from app.models import (  # noqa: E402
    analytics_event,
    ai_trial_usage,
    app_setting,
    device_token,
    match,
    message,
    message_reaction,
    profile,
    subscription,
    swipe,
    thread_read_state,
    user,
    user_block,
    user_ignore,
    user_report,
)

target_metadata = Base.metadata

ALEMBIC_VERSION_COLUMN_LIMIT = 128


def widened_version_table_impl(self, *, version_table, version_table_schema, version_table_pk, **kw):
    """Match Alembic's default version table, but allow longer revision IDs."""
    version_table_obj = Table(
        version_table,
        MetaData(),
        Column("version_num", String(ALEMBIC_VERSION_COLUMN_LIMIT), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        version_table_obj.append_constraint(
            PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
        )
    return version_table_obj


DefaultImpl.version_table_impl = widened_version_table_impl


def ensure_alembic_version_column_capacity(connection):
    """Ensure alembic_version.version_num can store long revision IDs."""
    if connection.dialect.name != "postgresql":
        return

    table_exists = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'alembic_version'
            )
            """
        )
    ).scalar()
    if not table_exists:
        if connection.in_transaction():
            connection.commit()
        return

    current_limit = connection.execute(
        text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'alembic_version'
              AND column_name = 'version_num'
            """
        )
    ).scalar()

    if current_limit is None or current_limit >= ALEMBIC_VERSION_COLUMN_LIMIT:
        if connection.in_transaction():
            connection.commit()
        return

    connection.execute(
        text(
            f"""
            ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_COLUMN_LIMIT})
            """
        )
    )
    if connection.in_transaction():
        connection.commit()

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        ensure_alembic_version_column_capacity(connection)
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
