"""Postgres fixtures: TEST_DATABASE_URL (CI) or a throwaway pgserver; schema via the backend Alembic migrations."""
import os
import tempfile
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))


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
def migrated_url(admin_url):
    name = "t_" + uuid.uuid4().hex[:12]
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = admin_url.rsplit("/", 1)[0] + "/" + name
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    yield url
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def session(migrated_url):
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        yield s
    engine.dispose()
