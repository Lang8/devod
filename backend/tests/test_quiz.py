import sys

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Passage, QuizAttempt, Sentence, Token, Topic, Word, WordTopic
from tests.test_auth_isolation import client, reg  # noqa: F401  (fixtures/helpers)

WORDS = [("gehen", "VERB", "가다", "gehe", "Ich gehe nach Hause."),
         ("laufen", "VERB", "달리다", "laufe", "Ich laufe schnell."),
         ("essen", "VERB", "먹다", "esse", "Ich esse Brot."),
         ("Haus", "NOUN", "집", "Haus", "Das Haus ist groß."),
         ("schön", "ADJ", "아름다운", "schöne", "Die schöne Stadt.")]


@pytest.fixture
def world(client):  # noqa: F811
    engine = create_engine(client.migrated_url)
    ids = {}
    with Session(engine) as s:
        t1 = Topic(slug="a", name_de="A", name_ko="가", level="A2")
        t2 = Topic(slug="b", name_de="B", name_ko="나", level="A2")
        s.add_all([t1, t2])
        s.flush()
        for t, ws in ((t1, WORDS[:3]), (t2, WORDS[3:])):
            p = Passage(topic_id=t.id, title="P", level="A2")
            s.add(p)
            s.flush()
            for i, (lemma, pos, ko, surf, text) in enumerate(ws):
                se = Sentence(passage_id=p.id, position=i, text_de=text, text_ko="번역")
                w = Word(lemma=lemma, pos=pos, meaning_ko=ko, gender="n" if lemma == "Haus" else None)
                s.add_all([se, w])
                s.flush()
                s.add(WordTopic(word_id=w.id, topic_id=t.id))
                tk = Token(sentence_id=se.id, position=1, surface=surf, lemma=lemma, pos=pos, word_id=w.id)
                s.add(tk)
                s.flush()
                ids[lemma] = tk.id
        s.commit()
        ids["topic_a"], ids["topic_b"] = t1.id, t2.id
    engine.dispose()
    h = reg(client, "q@example.com")
    for lemma, _, _, _, _ in WORDS:
        assert client.post("/discoveries", json={"token_id": ids[lemma]}, headers=h).status_code == 201
    return h, ids


def test_all_types_generated(client, world):
    h, _ = world
    qs = client.get("/quiz/questions?count=50", headers=h).json()
    assert {q["question_type"] for q in qs} == {"de_ko", "ko_de", "mcq", "cloze"}
    for q in qs:
        if q["question_type"] == "cloze":
            assert "_____" in q["prompt"] and q["hint"]
        if q["question_type"] == "mcq":
            assert len(q["choices"]) >= 2 and len(set(q["choices"])) == len(q["choices"])


def test_mcq_distractors_prefer_same_pos_from_vocab(client, world):
    h, _ = world
    qs = client.get("/quiz/questions?types=mcq&count=30", headers=h).json()
    vocab_meanings = {w[2] for w in WORDS}
    verbs = {"가다", "달리다", "먹다"}
    for q in qs:
        assert set(q["choices"]) <= vocab_meanings
        if q["prompt"] in ("gehen", "laufen", "essen"):
            assert set(q["choices"]) <= verbs | {"집", "아름다운"}
            assert len(set(q["choices"]) & verbs) == 3  # both other verbs used first


def test_topic_filter(client, world):
    h, ids = world
    qs = client.get(f"/quiz/questions?topic_id={ids['topic_b']}&types=de_ko&count=20", headers=h).json()
    assert qs and {q["prompt"] for q in qs} <= {"Haus", "schön"}
    qa = client.get(f"/quiz/questions?topic_id={ids['topic_a']}&types=de_ko&count=20", headers=h).json()
    assert {q["prompt"] for q in qa} <= {"gehen", "laufen", "essen"}


def test_invalid_params_and_empty_vocab(client, world):
    h, _ = world
    assert client.get("/quiz/questions?types=bogus", headers=h).status_code == 422
    assert client.get("/quiz/questions?count=0", headers=h).status_code == 422
    h2 = reg(client, "empty@example.com")
    assert client.get("/quiz/questions", headers=h2).json() == []
    assert client.get("/quiz/questions").status_code in (401, 403)


def test_grading_and_persistence(client, world):
    h, _ = world
    qs = client.get("/quiz/questions?count=50", headers=h).json()
    by_type = {}
    for q in qs:
        by_type.setdefault(q["question_type"], q)
    n = 0
    for qtype, q in by_type.items():
        prompt = q["prompt"]
        if qtype == "de_ko":
            right = {"gehen": "가다", "laufen": "달리다", "essen": "먹다", "Haus": "집", "schön": "아름다운"}[prompt]
        elif qtype == "mcq":
            right = {"gehen": "가다", "laufen": "달리다", "essen": "먹다", "Haus": "집", "schön": "아름다운"}[prompt]
        elif qtype == "ko_de":
            right = {"가다": "gehen", "달리다": "laufen", "먹다": "essen", "집": "Haus", "아름다운": "schön"}[prompt]
        else:
            right = next(w[3] for w in WORDS if w[4].replace(w[3], "_____", 1) == prompt)
        body = {"word_id": q["word_id"], "discovery_id": q["discovery_id"], "question_type": qtype}
        r = client.post("/quiz/answer", json={**body, "answer": right}, headers=h)
        assert r.status_code == 201 and r.json()["correct"] is True, (qtype, r.json())
        w = client.post("/quiz/answer", json={**body, "answer": "zzz"}, headers=h).json()
        assert w["correct"] is False and w["expected"]
        n += 2
    engine = create_engine(client.migrated_url)
    with Session(engine) as s:
        rows = list(s.scalars(select(QuizAttempt)))
    engine.dispose()
    assert len(rows) == n and {r.question_type for r in rows} == {"de_ko", "ko_de", "mcq", "cloze"}
    assert len(client.get("/quiz-attempts", headers=h).json()) == n


def test_answer_rules(client, world):
    h, ids = world
    d = client.get("/discoveries", headers=h).json()
    haus = next(x for x in d if x["word_lemma"] == "Haus")
    base = {"word_id": haus["word_id"], "discovery_id": haus["id"]}
    assert client.post("/quiz/answer", json={**base, "question_type": "ko_de", "answer": "das HAUS"},
                       headers=h).json()["correct"]
    assert client.post("/quiz/answer", json={**base, "question_type": "cloze", "answer": "haus"},
                       headers=h).json()["correct"]
    # other users cannot answer about words outside their vocabulary / others' discoveries
    h2 = reg(client, "other@example.com")
    assert client.post("/quiz/answer", json={**base, "question_type": "de_ko", "answer": "집"},
                       headers=h2).status_code == 404
    assert client.post("/quiz/answer", json={"word_id": haus["word_id"], "question_type": "cloze",
                                             "answer": "x"}, headers=h).status_code == 422


def test_no_llm_or_nlp_loaded():
    import app.main  # noqa: F401
    assert not any(m.split(".")[0] in ("anthropic", "spacy") for m in sys.modules)
