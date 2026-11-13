import os

from sqlalchemy import create_engine

from alembic import context
from app.models import Base

target_metadata = Base.metadata


def _url() -> str:
    url = context.config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.begin() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
