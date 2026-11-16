from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from app.models import Passage, Sentence, Topic
from tests.conftest import alembic_cfg
from tests.test_auth_isolation import client, reg  # noqa: F401  (fixture)

KEYS = {"source_title", "author", "source_url", "license", "adapted"}


def test_migration_backfills_license_on_existing_passages(empty_db_url):
    cfg = alembic_cfg(empty_db_url)
    command.upgrade(cfg, "0001")
    engine = create_engine(empty_db_url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO topic (slug,name_de,name_ko,level) VALUES ('t','T','티','A2')"))
        c.execute(text("INSERT INTO passage (topic_id,title,level,source) "
                       "SELECT id,'P','A2','llm' FROM topic"))
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        rows = c.execute(text("SELECT license, adapted FROM passage")).all()
        nullable = c.execute(text("SELECT is_nullable FROM information_schema.columns "
                                  "WHERE table_name='passage' AND column_name='license'")).scalar()
    assert rows == [("llm-generated", False)]
    assert nullable == "NO"
    engine.dispose()


def test_passage_api_returns_attribution(client):  # noqa: F811
    h = reg(client, "attr@example.com")
    engine = create_engine(client.migrated_url)
    with Session(engine) as s:
        t = Topic(slug="x", name_de="X", name_ko="엑스", level="B1")
        s.add(t)
        s.flush()
        a = Passage(topic_id=t.id, title="Wiki", level="B1", source="wikipedia",
                    source_title="Berlin", author="Wikipedia-Autoren",
                    source_url="https://de.wikipedia.org/wiki/Berlin",
                    license="CC BY-SA 4.0", adapted=True)
        b = Passage(topic_id=t.id, title="Old", level="B1")
        s.add_all([a, b])
        s.flush()
        s.add(Sentence(passage_id=a.id, position=0, text_de="Hallo.", text_ko="안녕."))
        s.commit()
        aid, bid, tid = a.id, b.id, t.id
    got = client.get(f"/passages/{aid}", headers=h)
    assert got.status_code == 200
    d = got.json()
    assert KEYS <= d.keys()
    assert (d["source_title"], d["author"], d["license"], d["adapted"]) == (
        "Berlin", "Wikipedia-Autoren", "CC BY-SA 4.0", True)
    assert d["source_url"] == "https://de.wikipedia.org/wiki/Berlin"
    old = client.get(f"/passages/{bid}", headers=h).json()
    assert old["license"] == "llm-generated" and old["adapted"] is False
    assert old["source_url"] is None
    lst = client.get(f"/topics/{tid}/passages", headers=h).json()
    assert all(KEYS <= r.keys() for r in lst)
    engine.dispose()
