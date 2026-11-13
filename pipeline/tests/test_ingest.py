"""Offline pipeline stores a topic passage with ordered sentences (de+ko) and per-token lemma/POS."""
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Passage, Sentence, Token, Topic
from deutsch_pipeline.analyze import load_nlp
from deutsch_pipeline.cli import main
from deutsch_pipeline.generate import FixtureGenerator, GeneratedPassage
from deutsch_pipeline.store import ingest_topic

FIXTURE = Path(__file__).parent.parent / "fixtures" / "umwelt.json"


@pytest.fixture(scope="module")
def nlp():
    return load_nlp()


class StubGenerator:
    def generate(self, topic_de, level, n_sentences):
        return GeneratedPassage(
            "Stub",
            [("Der Baum wächst.", "나무가 자란다."), ("Wir schützen die Natur.", "우리는 자연을 보호한다.")],
            "stub",
        )


def _assert_stored(session, topic_slug):
    topic = session.scalar(select(Topic).where(Topic.slug == topic_slug))
    passages = session.scalars(select(Passage).where(Passage.topic_id == topic.id)).all()
    assert len(passages) >= 1
    sents = session.scalars(
        select(Sentence).where(Sentence.passage_id == passages[0].id).order_by(Sentence.position)
    ).all()
    assert sents and [s.position for s in sents] == list(range(len(sents)))
    for s in sents:
        assert s.text_de and s.text_ko
        toks = session.scalars(select(Token).where(Token.sentence_id == s.id).order_by(Token.position)).all()
        assert toks and all(t.lemma and t.pos for t in toks)
        assert [t.position for t in toks] == list(range(len(toks)))
    return sents


def test_ingest_umwelt_fixture(session, nlp):
    ingest_topic(session, "umwelt", "A2", FixtureGenerator(FIXTURE), nlp)
    sents = _assert_stored(session, "umwelt")
    assert len(sents) == 3
    toks = session.scalars(select(Token).where(Token.sentence_id == sents[0].id)).all()
    by_surface = {t.surface: t for t in toks}
    assert by_surface["trennen"].lemma == "trennen" and by_surface["trennen"].pos == "VERB"
    assert by_surface["Müll"].pos == "NOUN"


def test_ingest_with_injected_stub(session, nlp):
    ingest_topic(session, "umwelt", "A2", StubGenerator(), nlp)
    assert len(_assert_stored(session, "umwelt")) == 2


def test_topic_reused_across_passages(session, nlp):
    ingest_topic(session, "umwelt", "A2", StubGenerator(), nlp)
    ingest_topic(session, "umwelt", "A2", StubGenerator(), nlp)
    assert len(session.scalars(select(Topic)).all()) == 1
    assert len(session.scalars(select(Passage)).all()) == 2


def test_cli_ingest_command(migrated_url):
    r = CliRunner().invoke(main, ["ingest", "--topic", "umwelt", "--level", "A2",
                                  "--fixture", str(FIXTURE), "--database-url", migrated_url])
    assert r.exit_code == 0, r.output
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        _assert_stored(s, "umwelt")
    engine.dispose()
