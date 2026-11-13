import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.learning import set_state
from app.models import (
    LEARNING_STATE_TYPES,
    Base,
    LearningState,
    LearningStateHistory,
    LearningStateType,
    Passage,
    Phrase,
    Sentence,
    Token,
    Topic,
    User,
    Word,
    WordTopic,
)
from tests.conftest import alembic_cfg

USER_ZONE = {"app_user", "discovery", "learning_state", "learning_state_history", "quiz_attempt"}
SHARED_ZONE = {"topic", "passage", "sentence", "token", "word", "word_topic", "phrase"}


def _user(s, email="a@b.c"):
    u = User(email=email, password_hash="x")
    s.add(u)
    s.flush()
    return u


def _word(s, lemma="Haus", pos="NOUN"):
    w = Word(lemma=lemma, pos=pos, meaning_ko="집")
    s.add(w)
    s.flush()
    return w


def test_migrations_apply_to_empty_postgres_and_match_models(empty_db_url):
    cfg = alembic_cfg(empty_db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(empty_db_url)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")  # re-applies cleanly
    engine.dispose()


def test_no_fk_from_shared_zone_to_user_zone(migrated_url):
    insp = inspect(create_engine(migrated_url))
    for t in SHARED_ZONE:
        for fk in insp.get_foreign_keys(t):
            assert fk["referred_table"] not in USER_ZONE, (t, fk)


def test_word_unique_lemma_pos(session):
    _word(session, "gehen", "VERB")
    _word(session, "gehen", "NOUN")  # same lemma, different pos is allowed
    with pytest.raises(IntegrityError):
        _word(session, "gehen", "VERB")


def test_learning_state_types_seeded(session):
    codes = set(session.scalars(select(LearningStateType.code)))
    assert codes == set(LEARNING_STATE_TYPES) == {
        "UNKNOWN", "UNFAMILIAR", "MEANING", "GENDER", "PLURAL", "INFLECTION", "CONTEXT", "EXPRESSION"}


def test_lookup_is_extensible_and_enforced(session):
    u, w = _user(session), _word(session)
    with pytest.raises(IntegrityError):  # unknown type rejected by FK
        set_state(session, u.id, w.id, "NEWTYPE", True)
    session.rollback()
    session.add(LearningStateType(code="NEWTYPE"))  # extension needs only a row
    session.flush()
    u, w = _user(session, "z@z.z"), _word(session, "x", "NOUN")
    assert set_state(session, u.id, w.id, "NEWTYPE", True).active


def test_multiple_active_states_per_user_word(session):
    u, w = _user(session), _word(session)
    for t in ("MEANING", "GENDER", "PLURAL"):
        set_state(session, u.id, w.id, t, True)
    rows = session.scalars(select(LearningState).where(
        LearningState.user_id == u.id, LearningState.word_id == w.id, LearningState.active)).all()
    assert {r.state_type for r in rows} == {"MEANING", "GENDER", "PLURAL"}
    session.add(LearningState(user_id=u.id, word_id=w.id, state_type="MEANING"))
    with pytest.raises(IntegrityError):  # unique (user, word, type)
        session.flush()


def test_history_written_on_every_state_change(session):
    u, w = _user(session), _word(session)
    ls = set_state(session, u.id, w.id, "MEANING", True)
    set_state(session, u.id, w.id, "MEANING", True)  # no change -> no row
    set_state(session, u.id, w.id, "MEANING", False)
    assert ls.resolved_at is not None
    set_state(session, u.id, w.id, "MEANING", True)
    assert ls.resolved_at is None
    events = session.scalars(select(LearningStateHistory.event).where(
        LearningStateHistory.learning_state_id == ls.id).order_by(LearningStateHistory.id)).all()
    assert events == ["added", "resolved", "reopened"]


def test_history_event_constrained(session):
    u, w = _user(session), _word(session)
    ls = set_state(session, u.id, w.id, "MEANING", True)
    session.add(LearningStateHistory(learning_state_id=ls.id, event="bogus"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_word_links_to_multiple_topics(session):
    w = _word(session)
    t1 = Topic(slug="travel", name_de="Reisen", name_ko="여행", level="A2")
    t2 = Topic(slug="home", name_de="Wohnen", name_ko="주거", level="A2")
    session.add_all([t1, t2])
    session.flush()
    session.add_all([WordTopic(word_id=w.id, topic_id=t1.id), WordTopic(word_id=w.id, topic_id=t2.id)])
    session.flush()
    assert set(session.scalars(select(WordTopic.topic_id).where(WordTopic.word_id == w.id))) == {t1.id, t2.id}
    session.add(WordTopic(word_id=w.id, topic_id=t1.id))
    with pytest.raises(IntegrityError):  # pair is unique
        session.flush()


def test_phrase_stores_multi_token_span(session):
    t = Topic(slug="t", name_de="T", name_ko="T", level="B1")
    session.add(t)
    session.flush()
    p = Passage(topic_id=t.id, title="P", level="B1")
    session.add(p)
    session.flush()
    s = Sentence(passage_id=p.id, position=0, text_de="Er gibt es zurück.", text_ko="그는 그것을 돌려준다.")
    session.add(s)
    session.flush()
    session.add_all([Token(sentence_id=s.id, position=i, surface=x, lemma=x, pos="X")
                     for i, x in enumerate(["Er", "gibt", "es", "zurück", "."])])
    ph = Phrase(text="gibt es zurück", meaning_ko="돌려준다", sentence_id=s.id, start_position=1, end_position=3)
    session.add(ph)
    session.flush()
    got = session.get(Phrase, ph.id)
    assert (got.text, got.end_position - got.start_position + 1) == ("gibt es zurück", 3)
    session.add(Phrase(text="bad", meaning_ko="x", sentence_id=s.id, start_position=3, end_position=1))
    with pytest.raises(IntegrityError):
        session.flush()
