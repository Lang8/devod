import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Passage, Sentence, Token, Topic, Word


@pytest.fixture
def client(migrated_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    from app import deps
    deps.get_engine.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        c.migrated_url = migrated_url
        yield c
    deps.get_engine.cache_clear()


@pytest.fixture
def token_id(client):
    engine = create_engine(client.migrated_url)
    with Session(engine) as s:
        t = Topic(slug="umwelt", name_de="Umwelt", name_ko="환경", level="A2")
        s.add(t)
        s.flush()
        p = Passage(topic_id=t.id, title="T", level="A2")
        s.add(p)
        s.flush()
        se = Sentence(passage_id=p.id, position=0, text_de="Ich gehe.", text_ko="나는 간다.")
        s.add(se)
        w = Word(lemma="gehen", pos="VERB", meaning_ko="가다")
        s.add(w)
        s.flush()
        tk = Token(sentence_id=se.id, position=1, surface="gehe", lemma="gehen", pos="VERB", word_id=w.id)
        s.add(tk)
        s.commit()
        tid = tk.id
    engine.dispose()
    return tid


def reg(client, email):
    r = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_register_login(client):
    reg(client, "a@example.com")
    dup = client.post("/auth/register", json={"email": "A@example.com", "password": "password123"})
    assert dup.status_code == 409
    ok = client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpass1"}).status_code == 401
    assert client.post("/auth/login", json={"email": "no@example.com", "password": "password123"}).status_code == 401
    assert client.post("/auth/register", json={"email": "bad", "password": "password123"}).status_code == 422
    h = {"Authorization": "Bearer " + ok.json()["access_token"]}
    assert client.get("/me", headers=h).json()["email"] == "a@example.com"


PROTECTED = [
    ("get", "/me"), ("get", "/discoveries"), ("post", "/discoveries"), ("get", "/discoveries/1"),
    ("get", "/vocabulary"), ("get", "/vocabulary/1"), ("get", "/quiz-attempts"),
    ("post", "/quiz-attempts"), ("get", "/quiz-attempts/1"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_requires_jwt(client, method, path):
    call = getattr(client, method)
    assert call(path).status_code == 401
    assert call(path, headers={"Authorization": "Bearer garbage"}).status_code == 401
    forged = jwt.encode({"sub": "1"}, "other-secret", algorithm="HS256")
    assert call(path, headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_cross_user_isolation(client, token_id):
    a, b = reg(client, "a@example.com"), reg(client, "b@example.com")
    d = client.post("/discoveries", json={"token_id": token_id}, headers=a)
    assert d.status_code == 201
    did, wid = d.json()["id"], d.json()["word_id"]
    qa = client.post("/quiz-attempts", json={"word_id": wid, "discovery_id": did, "question_type": "de_ko",
                                             "answer": "가다", "correct": True}, headers=a)
    assert qa.status_code == 201
    aid = qa.json()["id"]

    assert client.get(f"/discoveries/{did}", headers=a).status_code == 200
    assert client.get(f"/vocabulary/{wid}", headers=a).status_code == 200
    assert client.get(f"/quiz-attempts/{aid}", headers=a).status_code == 200
    assert len(client.get("/vocabulary", headers=a).json()) == 1

    assert client.get(f"/discoveries/{did}", headers=b).status_code == 404
    assert client.get(f"/vocabulary/{wid}", headers=b).status_code == 404
    assert client.get(f"/quiz-attempts/{aid}", headers=b).status_code == 404
    assert client.get("/discoveries", headers=b).json() == []
    assert client.get("/vocabulary", headers=b).json() == []
    assert client.get("/quiz-attempts", headers=b).json() == []
    attach = client.post("/quiz-attempts", json={"word_id": wid, "discovery_id": did, "question_type": "mcq",
                                                 "answer": "x", "correct": False}, headers=b)
    assert attach.status_code == 404


def test_content_browse_endpoints(client, token_id):
    assert client.get("/topics").status_code == 401
    h = reg(client, "browse@example.com")
    topics = client.get("/topics", headers=h).json()
    assert [t["slug"] for t in topics] == ["umwelt"]
    passages = client.get(f"/topics/{topics[0]['id']}/passages", headers=h).json()
    assert len(passages) == 1 and passages[0]["title"] == "T"
    p = client.get(f"/passages/{passages[0]['id']}", headers=h).json()
    assert [(s["position"], s["text_de"], s["text_ko"]) for s in p["sentences"]] == [
        (0, "Ich gehe.", "나는 간다.")]
    assert client.get("/topics/9999/passages", headers=h).status_code == 404
    assert client.get("/passages/9999", headers=h).status_code == 404


def test_discovery_details_second_discovery_and_lemma_override(client, token_id):
    engine = create_engine(client.migrated_url)
    with Session(engine) as s:
        old = s.get(Token, token_id)
        p2 = Passage(topic_id=s.get(Sentence, old.sentence_id).passage_id and
                     s.get(Passage, s.get(Sentence, old.sentence_id).passage_id).topic_id,
                     title="Zweiter Text", level="A2")
        s.add(p2)
        s.flush()
        se2 = Sentence(passage_id=p2.id, position=0, text_de="Wir gehen heim.", text_ko="우리는 집에 간다.")
        s.add(se2)
        s.flush()
        tk2 = Token(sentence_id=se2.id, position=1, surface="gehen", lemma="gehen", pos="VERB",
                    word_id=old.word_id)
        s.add(tk2)
        s.commit()
        token2 = tk2.id
        word_id = old.word_id
    engine.dispose()

    a, b = reg(client, "a@example.com"), reg(client, "b@example.com")
    # passage payload exposes clickable tokens
    pid = client.get("/topics", headers=a).json()[0]["id"]
    pas = client.get(f"/topics/{pid}/passages", headers=a).json()[0]["id"]
    toks = client.get(f"/passages/{pas}", headers=a).json()["sentences"][0]["tokens"]
    assert toks[0]["id"] == token_id and toks[0]["surface"] == "gehe"

    d1 = client.post("/discoveries", json={"token_id": token_id}, headers=a).json()
    d2 = client.post("/discoveries", json={"token_id": token2}, headers=a).json()
    assert d1["lemma"] == "gehen" and d1["surface_form"] == "gehe"
    assert d1["sentence_de"] == "Ich gehe." and d1["passage_title"] == "T" and d1["created_at"]
    assert d2["surface_form"] == "gehen" and d2["passage_title"] == "Zweiter Text"
    assert d1["id"] != d2["id"] and d1["word_id"] == d2["word_id"] == word_id

    vocab = client.get("/vocabulary", headers=a).json()
    assert len(vocab) == 1  # one Word, two Discoveries
    assert len(client.get(f"/vocabulary/{word_id}", headers=a).json()["discoveries"]) == 2

    # per-user override: only user A's discovery changes; shared Word unchanged
    ov = client.patch(f"/discoveries/{d1['id']}", json={"lemma_override": "laufen"}, headers=a)
    assert ov.status_code == 200 and ov.json()["lemma"] == "laufen" and ov.json()["word_lemma"] == "gehen"
    assert client.get(f"/discoveries/{d2['id']}", headers=a).json()["lemma"] == "gehen"
    assert client.get(f"/vocabulary/{word_id}", headers=a).json()["lemma"] == "gehen"
    db = client.post("/discoveries", json={"token_id": token_id}, headers=b).json()
    assert db["lemma"] == "gehen" and db["lemma_override"] is None
    assert client.patch(f"/discoveries/{d1['id']}", json={"lemma_override": "x"}, headers=b).status_code == 404
    cleared = client.patch(f"/discoveries/{d1['id']}", json={"lemma_override": None}, headers=a).json()
    assert cleared["lemma"] == "gehen"
    with Session(create_engine(client.migrated_url)) as s:
        assert s.get(Word, word_id).lemma == "gehen"
