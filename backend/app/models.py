"""ORM models. Shared zone (AI content) has no FK into the user zone."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


# ---------------- shared / AI-generated zone ----------------
class Topic(Base):
    __tablename__ = "topic"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_de: Mapped[str] = mapped_column(String(200))
    name_ko: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(2))


class Passage(Base):
    __tablename__ = "passage"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topic.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    level: Mapped[str] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(20), default="llm", server_default="llm")
    model_version: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(500), index=True)
    source_title: Mapped[str | None] = mapped_column(String(300))
    author: Mapped[str | None] = mapped_column(String(300))
    license: Mapped[str] = mapped_column(String(50), server_default="llm-generated")
    license_tier: Mapped[str] = mapped_column(String(12), server_default="open")
    source_level: Mapped[str | None] = mapped_column(String(2))
    adapted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sentence(Base):
    __tablename__ = "sentence"
    __table_args__ = (UniqueConstraint("passage_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    passage_id: Mapped[int] = mapped_column(ForeignKey("passage.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text_de: Mapped[str] = mapped_column(Text)
    text_ko: Mapped[str] = mapped_column(Text)


class Word(Base):
    __tablename__ = "word"
    __table_args__ = (UniqueConstraint("lemma", "pos", name="uq_word_lemma_pos"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lemma: Mapped[str] = mapped_column(String(200))
    pos: Mapped[str] = mapped_column(String(20))
    meaning_ko: Mapped[str] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(String(10))
    plural: Mapped[str | None] = mapped_column(String(200))
    conjugation: Mapped[dict | None] = mapped_column(JSONType)
    synonyms: Mapped[list | None] = mapped_column(JSONType)
    antonyms: Mapped[list | None] = mapped_column(JSONType)


class Token(Base):
    __tablename__ = "token"
    __table_args__ = (UniqueConstraint("sentence_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sentence_id: Mapped[int] = mapped_column(ForeignKey("sentence.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    surface: Mapped[str] = mapped_column(String(200))
    lemma: Mapped[str] = mapped_column(String(200))
    pos: Mapped[str] = mapped_column(String(20))
    separable_head_token_id: Mapped[int | None] = mapped_column(ForeignKey("token.id"))
    resolved_lemma: Mapped[str | None] = mapped_column(String(200))
    word_id: Mapped[int | None] = mapped_column(ForeignKey("word.id"), index=True)


class WordTopic(Base):
    __tablename__ = "word_topic"
    word_id: Mapped[int] = mapped_column(ForeignKey("word.id"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topic.id"), primary_key=True)


class Phrase(Base):
    __tablename__ = "phrase"
    __table_args__ = (
        CheckConstraint("end_position >= start_position", name="ck_phrase_span"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    meaning_ko: Mapped[str] = mapped_column(Text)
    sentence_id: Mapped[int] = mapped_column(ForeignKey("sentence.id"), index=True)
    start_position: Mapped[int] = mapped_column(Integer)
    end_position: Mapped[int] = mapped_column(Integer)


# ---------------- per-user zone ----------------
class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Discovery(Base):
    __tablename__ = "discovery"
    __table_args__ = (
        CheckConstraint("word_id IS NOT NULL OR phrase_id IS NOT NULL", name="ck_discovery_target"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    word_id: Mapped[int | None] = mapped_column(ForeignKey("word.id"), index=True)
    phrase_id: Mapped[int | None] = mapped_column(ForeignKey("phrase.id"))
    token_id: Mapped[int | None] = mapped_column(ForeignKey("token.id"))
    surface_form: Mapped[str] = mapped_column(String(200))
    sentence_id: Mapped[int] = mapped_column(ForeignKey("sentence.id"))
    passage_id: Mapped[int] = mapped_column(ForeignKey("passage.id"))
    lemma_override: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LearningStateType(Base):
    """Extensible lookup (rows, not an enum)."""
    __tablename__ = "learning_state_type"
    code: Mapped[str] = mapped_column(String(30), primary_key=True)


LEARNING_STATE_TYPES = [
    "UNKNOWN", "UNFAMILIAR", "MEANING", "GENDER", "PLURAL", "INFLECTION", "CONTEXT", "EXPRESSION",
]


class LearningState(Base):
    __tablename__ = "learning_state"
    __table_args__ = (UniqueConstraint("user_id", "word_id", "state_type", name="uq_learning_state"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("word.id"))
    state_type: Mapped[str] = mapped_column(ForeignKey("learning_state_type.code"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    history: Mapped[list["LearningStateHistory"]] = relationship(
        back_populates="learning_state", order_by="LearningStateHistory.id"
    )


class LearningStateHistory(Base):
    __tablename__ = "learning_state_history"
    __table_args__ = (
        CheckConstraint("event IN ('added','resolved','reopened')", name="ck_history_event"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    learning_state_id: Mapped[int] = mapped_column(ForeignKey("learning_state.id"), index=True)
    event: Mapped[str] = mapped_column(String(10))
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    learning_state: Mapped[LearningState] = relationship(back_populates="history")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempt"
    __table_args__ = (
        CheckConstraint("question_type IN ('de_ko','ko_de','mcq','cloze')", name="ck_quiz_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("word.id"))
    discovery_id: Mapped[int | None] = mapped_column(ForeignKey("discovery.id"))
    question_type: Mapped[str] = mapped_column(String(10))
    answer: Mapped[str] = mapped_column(Text)
    correct: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
