"""AC5: rerun skips, --force adds, and a batch manifest isolates failing entries."""
from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Passage, Sentence
from deutsch_pipeline.cli import main
from deutsch_pipeline.ingest_source import ingest_source

from .ingest_fakes import (SENTS, FakeLLM, Transport, cli_args, cli_obj, client_for, count, entry,
                           wiki_body, write_manifest)


def test_rerun_skips_and_force_adds(session, nlp):
    kw = dict(kind="wikipedia", ref="Berlin", topic="stadt", level="A2", llm=FakeLLM(), nlp=nlp)
    first = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])), **kw)
    before = session.scalars(select(Sentence.text_de).where(Sentence.passage_id == first.passage_id)).all()
    again = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])), **kw)
    assert again.skipped and again.passage_id == first.passage_id and count(session) == 1
    assert session.scalars(select(Sentence.text_de).where(Sentence.passage_id == first.passage_id)).all() == before
    other = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])),
                          **{**kw, "level": "B1"})
    assert not other.skipped and count(session) == 2  # different level is not a duplicate
    forced = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])), force=True, **kw)
    assert not forced.skipped and forced.passage_id != first.passage_id and count(session) == 3
    assert session.get(Passage, first.passage_id) is not None


def test_cli_rerun_skip_and_force(migrated_url, nlp):
    engine = create_engine(migrated_url)

    def rows():
        with Session(engine) as s:
            return count(s)

    assert CliRunner().invoke(main, cli_args(migrated_url), obj=cli_obj(wiki_body(SENTS))).exit_code == 0
    r = CliRunner().invoke(main, cli_args(migrated_url), obj=cli_obj(wiki_body(SENTS)))
    assert r.exit_code == 0 and "SKIPPED" in r.output and rows() == 1
    r = CliRunner().invoke(main, cli_args(migrated_url, "--force"), obj=cli_obj(wiki_body(SENTS)))
    assert r.exit_code == 0 and rows() == 2
    engine.dispose()


def test_manifest_skips_existing_isolates_failures_and_exits_nonzero(migrated_url, nlp, tmp_path):
    engine = create_engine(migrated_url)

    def rows():
        with Session(engine) as s:
            return count(s)

    assert CliRunner().invoke(main, cli_args(migrated_url), obj=cli_obj(wiki_body(SENTS))).exit_code == 0
    m = write_manifest(tmp_path, [entry("Berlin"), entry("Leer"), entry("Hamburg")])
    obj = cli_obj(wiki_body(SENTS, "Berlin"), wiki_body([], "Leer"), wiki_body(SENTS, "Hamburg"))
    res = CliRunner().invoke(main, ["ingest-manifest", m, "--database-url", migrated_url], obj=obj)
    assert res.exit_code != 0
    assert "SKIPPED" in res.output and "FAILED" in res.output
    assert "1 stored, 1 skipped, 1 failed" in res.output
    assert rows() == 2  # failure neither undid Berlin nor blocked Hamburg
    m2 = write_manifest(tmp_path, [entry("Berlin"), entry("Hamburg")])
    obj = cli_obj(wiki_body(SENTS, "Berlin"), wiki_body(SENTS, "Hamburg"))
    res = CliRunner().invoke(main, ["ingest-manifest", m2, "--database-url", migrated_url], obj=obj)
    assert res.exit_code == 0 and "2 skipped" in res.output and rows() == 2
    engine.dispose()


def test_manifest_fetch_failure_does_not_block_batch(migrated_url, nlp, tmp_path):
    m = write_manifest(tmp_path, [entry("Boom"), entry("Hamburg")])
    obj = {"transport": Transport([TimeoutError("x"), TimeoutError("x"), TimeoutError("x"),
                                   (200, wiki_body(SENTS, "Hamburg"))]),
           "llm": FakeLLM(), "nlp": nlp}
    res = CliRunner().invoke(main, ["ingest-manifest", m, "--database-url", migrated_url], obj=obj)
    assert res.exit_code != 0 and "1 stored" in res.output and "1 failed" in res.output
