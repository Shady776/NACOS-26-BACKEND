from logging.config import fileConfig

from alembic import context

from app.database import engine, SQLALCHEMY_DATABASE_URL
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=SQLALCHEMY_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # A brand-new, empty database (first deploy) has no tables for the migrations to
    # alter. Create any missing tables first; on an existing database this only adds
    # tables that are missing and never touches existing ones.
    Base.metadata.create_all(bind=engine)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rebuilds the table.
            render_as_batch=IS_SQLITE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()