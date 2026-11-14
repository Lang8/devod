"""AC1: ingest one named Wikipedia/Wikinews/Gutenberg source offline, with attribution;
empty, too-short and timed-out sources are rejected and write nothing."""
import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Passage, Sentence
from deutsch_pipeline.cli import main
from deutsch_pipeline.http import USER_AGENT
from deutsch_pipeline.ingest_source import IngestError, ingest_source

from .ingest_fakes import (SENTS, FakeLLM, Transport, client_for, count, wiki_body)


def test_wikipedia_verbatim_with_attribution(session, nlp):
    t = Transport([(200, wiki_body(SENTS))])
    res = ingest_source(session, kind="wikipedia", ref="Berlin", topic="stadt", level="A2",
                        client=client_for(t), llm=FakeLLM("A1"), nlp=nlp)
    p = session.get(Passage, res.passage_id)
    assert p.source_url == "https://de.wikipedia.org/wiki/Berlin"
    assert (p.source_title, p.license, p.license_tier) == ("Berlin", "CC BY-SA 4.0", "open")
    assert p.author and p.source_level == "A1" and p.level == "A2" and p.adapted is False
    sents = session.scalars(select(Sentence).where(Sentence.passage_id == p.id).order_by(Sentence.position)).all()
    assert 5 <= len(sents) <= 7
    assert sents[0].text_de == "Einleitung." or sents[0].text_de.startswith("Das ist")
    assert all(s.text_de and s.text_ko for s in sents)
    assert t.calls[0][1]["User-Agent"] == USER_AGENT and t.calls[0][2] == 30


def test_wikinews_and_gutenberg(session, nlp):
    body = wiki_body(SENTS, "Nachricht")
    ingest_source(session, kind="wikinews", ref="https://de.wikinews.org/wiki/Nachricht", topic="n",
                  level="A2", client=client_for(Transport([(200, body)])), llm=FakeLLM(), nlp=nlp)
    p = session.scalars(select(Passage)).one()
    assert p.license == "CC BY 2.5" and p.source_url == "https://de.wikinews.org/wiki/Nachricht"

    book = ("Title: Der Test\nAuthor: Anna Autor\n\n*** START OF THE PROJECT GUTENBERG EBOOK DER TEST ***\n\n"
            + "\n\n".join(" ".join(SENTS[i:i + 3]) for i in (0, 3, 6, 9)) + "\n\n*** END OF THE PROJECT GUTENBERG EBOOK ***\nlicense")
    ingest_source(session, kind="gutenberg", ref="1234", topic="g", level="A2",
                  client=client_for(Transport([(200, book)])), llm=FakeLLM(), nlp=nlp)
    g = session.scalars(select(Passage).where(Passage.source == "gutenberg")).one()
    assert (g.source_title, g.author, g.license) == ("Der Test", "Anna Autor", "Public Domain")
    assert g.source_url == "https://www.gutenberg.org/ebooks/1234"


def test_empty_and_short_sources_rejected(session, nlp):
    for sents in ([], SENTS[:3]):
        with pytest.raises(IngestError):
            ingest_source(session, kind="wikipedia", ref="Leer", topic="x", level="A2",
                          client=client_for(Transport([(200, wiki_body(sents))])), llm=FakeLLM(), nlp=nlp)
    assert count(session) == 0


def test_fetch_timeout_three_attempts_nothing_written(session, nlp):
    t = Transport([TimeoutError("timed out")])
    with pytest.raises(IngestError):
        ingest_source(session, kind="wikipedia", ref="Berlin", topic="x", level="A2",
                      client=client_for(t), llm=FakeLLM(), nlp=nlp)
    assert len(t.calls) == 3 and all(c[2] == 30 for c in t.calls)
    assert count(session) == 0


def test_cli_rejects_nonzero_and_succeeds(migrated_url, nlp):
    args = ["ingest-source", "--kind", "wikipedia", "--ref", "Berlin", "--topic", "stadt", "--level", "A2",
            "--database-url", migrated_url]
    bad = CliRunner().invoke(main, args, obj={"transport": Transport([(200, wiki_body([]))]),
                                              "llm": FakeLLM(), "nlp": nlp})
    assert bad.exit_code != 0
    ok = CliRunner().invoke(main, args, obj={"transport": Transport([(200, wiki_body(SENTS))]),
                                             "llm": FakeLLM(), "nlp": nlp})
    assert ok.exit_code == 0, ok.output
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        assert count(s) == 1
    engine.dispose()
