"""Seed a tiny deterministic topic/passage (with resolved Words) for the Playwright E2E.

Shared-zone rows only; no spaCy/LLM involved. Usage: DATABASE_URL=... python scripts/seed_e2e.py
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Passage, Sentence, Token, Topic, Word, WordTopic


def url() -> str:
    u = os.environ["DATABASE_URL"]
    for p in ("postgresql://", "postgres://"):
        if u.startswith(p):
            return "postgresql+psycopg://" + u[len(p):]
    return u


def main() -> None:
    with Session(create_engine(url())) as s:
        topic = Topic(slug="umwelt", name_de="Umwelt", name_ko="환경", level="A2")
        s.add(topic)
        s.flush()
        passage = Passage(topic_id=topic.id, title="Müll trennen", level="A2", source="llm",
                          model_version="e2e-seed")
        s.add(passage)
        s.flush()
        words = {
            "Müll": Word(lemma="Müll", pos="NOUN", meaning_ko="쓰레기", gender="der", plural="Müll"),
            "Umwelt": Word(lemma="Umwelt", pos="NOUN", meaning_ko="환경", gender="die", plural="Umwelten"),
        }
        s.add_all(words.values())
        s.flush()
        for w in words.values():
            s.add(WordTopic(word_id=w.id, topic_id=topic.id))
        text_de, text_ko = "Der Müll schadet der Umwelt.", "쓰레기는 환경에 해롭다."
        sent = Sentence(passage_id=passage.id, position=0, text_de=text_de, text_ko=text_ko)
        s.add(sent)
        s.flush()
        for pos, surface in enumerate(["Der", "Müll", "schadet", "der", "Umwelt", "."]):
            w = words.get(surface)
            s.add(Token(sentence_id=sent.id, position=pos, surface=surface, lemma=surface,
                        pos="NOUN" if w else "X", word_id=w.id if w else None))
        s.commit()


if __name__ == "__main__":
    main()
