"""AC2: restricted (local file) content needs --allow-restricted AND an exactly-local DB host;
otherwise the run is refused, exits non-zero and writes nothing."""
import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Passage
from deutsch_pipeline.cli import main
from deutsch_pipeline.ingest_source import IngestError, ingest_source
from deutsch_pipeline.sources import is_local_db_url

from .ingest_fakes import (FakeLLM, Transport, client_for, count, restricted_file, write_manifest)


@pytest.mark.parametrize("url,expected", [
    ("postgresql://u:p@localhost:5432/db", True),
    ("postgresql://u:p@127.0.0.1/db", True),
    ("postgresql://u:p@[::1]:5432/db", True),
    ("postgresql://u:p@localhost.evil.com/db", False),
    ("postgresql://localhost@evil.com/db", False),
    ("postgresql://u:localhost@db.supabase.co/db", False),
    ("postgresql://u:p@db.example.com/db?host=localhost", False),
    ("postgresql://u:p@127.0.0.1.evil.com/db", False),
    ("postgresql:///db", False),
])
def test_is_local_db_url(url, expected):
    assert is_local_db_url(url) is expected


def test_restricted_requires_flag_and_writes_nothing(session, nlp, tmp_path):
    ref = restricted_file(tmp_path)
    with pytest.raises(IngestError):
        ingest_source(session, kind="local_file", ref=ref, topic="stadt", level="A2",
                      client=client_for(Transport([(200, "")])), llm=FakeLLM(), nlp=nlp)
    assert count(session) == 0


def test_restricted_refused_for_nonlocal_host(nlp, tmp_path, monkeypatch):
    from sqlalchemy.engine import make_url

    class Bind:
        url = make_url("postgresql://u:p@localhost.evil.com/db")

    class Sess:
        def get_bind(self):
            return Bind()

    with pytest.raises(IngestError, match="local database"):
        ingest_source(Sess(), kind="local_file", ref=restricted_file(tmp_path), topic="stadt", level="A2",
                      client=client_for(Transport([(200, "")])), llm=FakeLLM(), nlp=nlp,
                      allow_restricted=True)


def test_restricted_allowed_on_local_db(session, nlp, tmp_path):
    res = ingest_source(session, kind="local_file", ref=restricted_file(tmp_path), topic="stadt", level="A2",
                        client=client_for(Transport([(200, "")])), llm=FakeLLM(), nlp=nlp,
                        allow_restricted=True)
    assert count(session) == 1
    p = session.get(Passage, res.passage_id)
    assert p.license_tier == "restricted" and p.source_title == "Goethe A2 Modelltest"


def test_cli_restricted_flag_and_host(migrated_url, nlp, tmp_path):
    ref = restricted_file(tmp_path)
    base = ["ingest-source", "--kind", "local_file", "--ref", ref, "--topic", "stadt", "--level", "A2"]
    obj = {"llm": FakeLLM(), "nlp": nlp}
    engine = create_engine(migrated_url)

    def rows():
        with Session(engine) as s:
            return count(s)

    no_flag = CliRunner().invoke(main, base + ["--database-url", migrated_url], obj=obj)
    assert no_flag.exit_code != 0 and rows() == 0
    evil = migrated_url.replace("@localhost", "@localhost.evil.com").replace("@127.0.0.1", "@127.0.0.1.evil.com")
    bad = CliRunner().invoke(main, base + ["--allow-restricted", "--database-url", evil], obj=obj)
    assert bad.exit_code != 0 and rows() == 0
    ok = CliRunner().invoke(main, base + ["--allow-restricted", "--database-url", migrated_url], obj=obj)
    local = is_local_db_url(migrated_url)
    assert (ok.exit_code == 0) == local, ok.output
    assert rows() == (1 if local else 0)
    engine.dispose()


def test_manifest_restricted_entry_refused_without_flag(migrated_url, nlp, tmp_path):
    m = write_manifest(tmp_path, [{"kind": "local_file", "ref": restricted_file(tmp_path),
                              "topic": "stadt", "level": "A2"}])
    res = CliRunner().invoke(main, ["ingest-manifest", m, "--database-url", migrated_url],
                             obj={"llm": FakeLLM(), "nlp": nlp})
    assert res.exit_code != 0
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        assert count(s) == 0
    engine.dispose()
