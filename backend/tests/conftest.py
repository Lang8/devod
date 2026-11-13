"""Postgres fixtures. Uses TEST_DATABASE_URL (CI service container) if set,
otherwise spins up a throwaway local Postgres via pgserver."""
import os
import tempfile
import uuid

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command


def _psycopg(url: str) -> str:
    for p in ("postgresql://", "postgres://"):
        if url.startswith(p):
            return "postgresql+psycopg://" + url[len(p):]
    return url


@pytest.fixture(scope="session")
def admin_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield _psycopg(url)
        return
    import pgserver

    with tempfile.TemporaryDirectory() as d:
        srv = pgserver.get_server(d, cleanup_mode="stop")
        yield _psycopg(srv.get_uri())
        srv.cleanup()


@pytest.fixture
def empty_db_url(admin_url):
    """A brand-new empty database."""
    name = "t_" + uuid.uuid4().hex[:12]
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = admin_url.rsplit("/", 1)[0] + "/" + name
    yield url
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def alembic_cfg(url: str) -> Config:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture
def migrated_url(empty_db_url):
    command.upgrade(alembic_cfg(empty_db_url), "head")
    return empty_db_url


@pytest.fixture
def session(migrated_url):
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        yield s
    engine.dispose()
