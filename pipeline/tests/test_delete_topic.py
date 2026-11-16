"""delete --topic: transactional, dry-run by default, protects real-user data."""
import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    Discovery, LearningState, Passage, Phrase, QuizAttempt, Sentence,
    Token, Topic, User, Word, WordTopic,
)
from deutsch_pipeline.cli import main
from deutsch_pipeline.generate import GeneratedPassage
from deutsch_pipeline.store import ingest_topic

TEST_EMAIL = "e2e@example.com"
TABLES = [Topic, Passage, Sentence, Token, Phrase, Word, WordTopic, Discovery, LearningState, QuizAttempt]


class Stub:
    def generate(self, topic_de, level, n):
        return GeneratedPassage("Stub", [("Der Baum wächst.", "a")], "stub")


def counts(url):
    e = create_engine(url)
    with Session(e) as s:
        r = {m.__name__: s.scalar(select(func.count()).select_from(m)) for m in TABLES}
    e.dispose()
    return r


@pytest.fixture
def seeded(migrated_url):
    e = create_engine(migrated_url)
    with Session(e) as s:
        a = Topic(slug="umwelt", name_de="U", name_ko="u", level="A2")
        b = Topic(slug="reisen", name_de="R", name_ko="r", level="A2")
        s.add_all([a, b, User(email=TEST_EMAIL, password_hash="x"), User(email="real@x.com", password_hash="x")])
        s.flush()
        pa = Passage(topic_id=a.id, title="t", level="A2")
        pb = Passage(topic_id=b.id, title="t", level="A2")
        s.add_all([pa, pb]); s.flush()
        sa = Sentence(passage_id=pa.id, position=0, text_de="d", text_ko="k")
        sb = Sentence(passage_id=pb.id, position=0, text_de="d", text_ko="k")
        s.add_all([sa, sb]); s.flush()
        shared = Word(lemma="Baum", pos="NOUN", meaning_ko="m")
        orphan = Word(lemma="Müll", pos="NOUN", meaning_ko="m")
        s.add_all([shared, orphan]); s.flush()
        s.add_all([WordTopic(word_id=shared.id, topic_id=a.id), WordTopic(word_id=shared.id, topic_id=b.id),
                   WordTopic(word_id=orphan.id, topic_id=a.id)])
        ta = Token(sentence_id=sa.id, position=0, surface="Müll", lemma="Müll", pos="NOUN", word_id=orphan.id)
        tb = Token(sentence_id=sb.id, position=0, surface="Baum", lemma="Baum", pos="NOUN", word_id=shared.id)
        s.add_all([ta, tb, Phrase(text="p", meaning_ko="m", sentence_id=sa.id, start_position=0, end_position=0)])
        s.flush()
        tu = s.scalar(select(User.id).where(User.email == TEST_EMAIL))
        d = Discovery(user_id=tu, word_id=orphan.id, token_id=ta.id, surface_form="Müll",
                      sentence_id=sa.id, passage_id=pa.id)
        s.add(d); s.flush()
        s.add_all([QuizAttempt(user_id=tu, word_id=orphan.id, discovery_id=d.id, question_type="mcq",
                               answer="a", correct=True),
                   LearningState(user_id=tu, word_id=orphan.id, state_type="UNKNOWN")])
        s.commit()
    e.dispose()
    return migrated_url


def run(url, *extra):
    return CliRunner().invoke(main, ["delete", "--topic", "umwelt", "--database-url", url,
                                     "--test-account-email", TEST_EMAIL, *extra])


def test_dry_run_changes_nothing(seeded):
    before = counts(seeded)
    r = run(seeded)
    assert r.exit_code == 0 and "DRY-RUN" in r.output and "word_orphans: 1" in r.output
    assert counts(seeded) == before


def test_delete_yes_keeps_shared_word_removes_orphan_and_is_idempotent(seeded):
    r = run(seeded, "--yes")
    assert r.exit_code == 0, r.output
    c = counts(seeded)
    assert c["Topic"] == 1 and c["Passage"] == 1 and c["Sentence"] == 1 and c["Token"] == 1
    assert c["Phrase"] == 0 and c["Word"] == 1 and c["WordTopic"] == 1
    assert c["Discovery"] == c["LearningState"] == c["QuizAttempt"] == 0
    e = create_engine(seeded)
    with Session(e) as s:
        assert s.scalar(select(Word.lemma)) == "Baum"
    e.dispose()
    again = run(seeded, "--yes")
    assert again.exit_code == 0 and "not found" in again.output


def test_refuses_when_other_user_references_topic(seeded):
    e = create_engine(seeded)
    with Session(e) as s:
        uid = s.scalar(select(User.id).where(User.email == "real@x.com"))
        t = s.scalar(select(Token).where(Token.surface == "Müll"))
        s.add(Discovery(user_id=uid, word_id=t.word_id, token_id=t.id, surface_form="Müll",
                        sentence_id=t.sentence_id,
                        passage_id=s.scalar(select(Sentence.passage_id).where(Sentence.id == t.sentence_id))))
        s.commit()
    e.dispose()
    before = counts(seeded)
    r = run(seeded, "--yes")
    assert r.exit_code != 0 and "REFUSED" in r.output
    assert counts(seeded) == before  # test-account data untouched too


def test_reingest_after_delete(seeded):
    assert run(seeded, "--yes").exit_code == 0
    from deutsch_pipeline.analyze import load_nlp
    e = create_engine(seeded)
    with Session(e) as s:
        ingest_topic(s, "umwelt", "A2", Stub(), load_nlp())
        assert s.scalar(select(func.count()).select_from(Passage)) == 2
    e.dispose()
