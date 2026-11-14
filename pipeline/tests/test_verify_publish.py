"""verify-publish: counts against the test Postgres; read-only; non-zero on any mismatch."""
from click.testing import CliRunner
from sqlalchemy import func, select
from sqlalchemy.orm import Session  # noqa: F401

from app.models import Passage, Topic
from deutsch_pipeline.cli import main
from deutsch_pipeline.verify_publish import LEVELS, verify_publish


def _topic(session):
    t = Topic(slug="vp", name_de="VP", name_ko="VP", level="A1")
    session.add(t)
    session.flush()
    return t


def _add(session, topic, level, n, tier="open", license="CC BY-SA 4.0", author="Autoren"):
    for i in range(n):
        session.add(Passage(topic_id=topic.id, title=f"{level}{i}", level=level, source="wikipedia",
                            source_url=f"https://de.wikipedia.org/wiki/{level}{i}{tier}",
                            source_title="T", author=author, license=license, license_tier=tier))


def _full(session):
    t = _topic(session)
    for lv in LEVELS:
        _add(session, t, lv, 2)
    session.commit()
    return t


def test_ok_when_12_open_two_per_level(session):
    _full(session)
    rep = verify_publish(session)
    assert rep.ok and rep.open_total == 12 and rep.restricted_total == 0
    assert all(rep.open_by_level[lv] == 2 for lv in LEVELS)


def test_llm_generated_passages_do_not_count(session):
    t = _full(session)
    session.add(Passage(topic_id=t.id, title="llm", level="A1"))
    session.commit()
    assert verify_publish(session).ok


def test_mismatches_fail(session):
    t = _full(session)
    _add(session, t, "A1", 1)  # 13 total, A1 has 3
    session.commit()
    rep = verify_publish(session)
    assert not rep.ok and rep.open_total == 13


def test_missing_level_fails(session):
    t = _topic(session)
    for lv in LEVELS[:-1]:
        _add(session, t, lv, 2)
    session.commit()
    rep = verify_publish(session)
    assert not rep.ok and any("C2" in p for p in rep.problems)


def test_restricted_present_fails(session):
    t = _full(session)
    _add(session, t, "B1", 1, tier="restricted", license="restricted")
    session.commit()
    rep = verify_publish(session)
    assert not rep.ok and rep.restricted_total == 1


def test_missing_attribution_fails(session):
    t = _topic(session)
    for lv in LEVELS:
        _add(session, t, lv, 2, author="" if lv == "C2" else "Autoren")
    session.commit()
    rep = verify_publish(session)
    assert not rep.ok and rep.missing_attribution == 2


def test_cli_exit_codes_and_read_only(migrated_url):
    from sqlalchemy import create_engine

    engine = create_engine(migrated_url)
    with Session(engine) as s:
        _full(s)
    r = CliRunner().invoke(main, ["verify-publish", "--database-url", migrated_url])
    assert r.exit_code == 0, r.output
    assert "verify-publish: OK" in r.output
    with Session(engine) as s:
        _add(s, s.scalar(select(Topic)), "C2", 1)
        s.commit()
        before = s.scalar(select(func.count()).select_from(Passage))
    r = CliRunner().invoke(main, ["verify-publish", "--database-url", migrated_url])
    assert r.exit_code == 1
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Passage)) == before
    engine.dispose()
