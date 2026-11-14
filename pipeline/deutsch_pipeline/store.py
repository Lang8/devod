"""DB stage: persist topic, passage, ordered sentences and per-token rows."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Passage, Sentence, Token, Topic

from .analyze import analyze_sentence
from .generate import GeneratedPassage

TOPIC_CATALOG = {
    "umwelt": ("Umwelt", "환경"),
    "reisen": ("Reisen", "여행"),
    "essen": ("Essen und Trinken", "음식"),
    "arbeit": ("Arbeit", "직업"),
}


def get_or_create_topic(session: Session, slug: str, level: str, name_de: str | None = None,
                        name_ko: str | None = None) -> Topic:
    topic = session.scalar(select(Topic).where(Topic.slug == slug))
    if topic:
        return topic
    default_de, default_ko = TOPIC_CATALOG.get(slug, (slug.capitalize(), slug))
    topic = Topic(slug=slug, name_de=name_de or default_de, name_ko=name_ko or default_ko, level=level)
    session.add(topic)
    session.flush()
    return topic


def store_passage(session: Session, topic: Topic, level: str, generated: GeneratedPassage, nlp,
                  provenance: dict | None = None) -> Passage:
    fields = {"source": "llm", **(provenance or {})}
    passage = Passage(topic_id=topic.id, title=generated.title, level=level,
                      model_version=generated.model_version, **fields)
    session.add(passage)
    session.flush()
    for pos, (de, ko) in enumerate(generated.sentences):
        sent = Sentence(passage_id=passage.id, position=pos, text_de=de, text_ko=ko)
        session.add(sent)
        session.flush()
        for t in analyze_sentence(nlp, de):
            session.add(Token(sentence_id=sent.id, position=t.position, surface=t.surface,
                              lemma=t.lemma, pos=t.pos))
    session.flush()
    return passage


def ingest_topic(session: Session, slug: str, level: str, generator, nlp, n_sentences: int = 6,
                 name_de: str | None = None, name_ko: str | None = None) -> Passage:
    topic = get_or_create_topic(session, slug, level, name_de, name_ko)
    generated = generator.generate(topic.name_de, level, n_sentences)
    passage = store_passage(session, topic, level, generated, nlp)
    session.commit()
    return passage
