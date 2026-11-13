"""initial schema: shared content zone + per-user zone

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONT = sa.JSON().with_variant(JSONB(), "postgresql")
STATE_TYPES = ["UNKNOWN", "UNFAMILIAR", "MEANING", "GENDER", "PLURAL", "INFLECTION", "CONTEXT", "EXPRESSION"]


def _pk():
    return sa.Column("id", sa.Integer, primary_key=True)


def upgrade() -> None:
    # ---- shared zone ----
    op.create_table(
        "topic", _pk(),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("name_de", sa.String(200), nullable=False),
        sa.Column("name_ko", sa.String(200), nullable=False),
        sa.Column("level", sa.String(2), nullable=False),
    )
    op.create_table(
        "passage", _pk(),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topic.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("level", sa.String(2), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="llm"),
        sa.Column("model_version", sa.String(100)),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_passage_topic_id", "passage", ["topic_id"])
    op.create_table(
        "sentence", _pk(),
        sa.Column("passage_id", sa.Integer, sa.ForeignKey("passage.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("text_de", sa.Text, nullable=False),
        sa.Column("text_ko", sa.Text, nullable=False),
        sa.UniqueConstraint("passage_id", "position"),
    )
    op.create_index("ix_sentence_passage_id", "sentence", ["passage_id"])
    op.create_table(
        "word", _pk(),
        sa.Column("lemma", sa.String(200), nullable=False),
        sa.Column("pos", sa.String(20), nullable=False),
        sa.Column("meaning_ko", sa.Text, nullable=False),
        sa.Column("gender", sa.String(10)),
        sa.Column("plural", sa.String(200)),
        sa.Column("conjugation", JSONT),
        sa.Column("synonyms", JSONT),
        sa.Column("antonyms", JSONT),
        sa.UniqueConstraint("lemma", "pos", name="uq_word_lemma_pos"),
    )
    op.create_table(
        "token", _pk(),
        sa.Column("sentence_id", sa.Integer, sa.ForeignKey("sentence.id"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("surface", sa.String(200), nullable=False),
        sa.Column("lemma", sa.String(200), nullable=False),
        sa.Column("pos", sa.String(20), nullable=False),
        sa.Column("separable_head_token_id", sa.Integer, sa.ForeignKey("token.id")),
        sa.Column("resolved_lemma", sa.String(200)),
        sa.Column("word_id", sa.Integer, sa.ForeignKey("word.id")),
        sa.UniqueConstraint("sentence_id", "position"),
    )
    op.create_index("ix_token_sentence_id", "token", ["sentence_id"])
    op.create_index("ix_token_word_id", "token", ["word_id"])
    op.create_table(
        "word_topic",
        sa.Column("word_id", sa.Integer, sa.ForeignKey("word.id"), primary_key=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topic.id"), primary_key=True),
    )
    op.create_table(
        "phrase", _pk(),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("meaning_ko", sa.Text, nullable=False),
        sa.Column("sentence_id", sa.Integer, sa.ForeignKey("sentence.id"), nullable=False),
        sa.Column("start_position", sa.Integer, nullable=False),
        sa.Column("end_position", sa.Integer, nullable=False),
        sa.CheckConstraint("end_position >= start_position", name="ck_phrase_span"),
    )
    op.create_index("ix_phrase_sentence_id", "phrase", ["sentence_id"])

    # ---- user zone ----
    op.create_table(
        "app_user", _pk(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "discovery", _pk(),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("word_id", sa.Integer, sa.ForeignKey("word.id")),
        sa.Column("phrase_id", sa.Integer, sa.ForeignKey("phrase.id")),
        sa.Column("token_id", sa.Integer, sa.ForeignKey("token.id")),
        sa.Column("surface_form", sa.String(200), nullable=False),
        sa.Column("sentence_id", sa.Integer, sa.ForeignKey("sentence.id"), nullable=False),
        sa.Column("passage_id", sa.Integer, sa.ForeignKey("passage.id"), nullable=False),
        sa.Column("lemma_override", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("word_id IS NOT NULL OR phrase_id IS NOT NULL", name="ck_discovery_target"),
    )
    op.create_index("ix_discovery_user_id", "discovery", ["user_id"])
    op.create_index("ix_discovery_word_id", "discovery", ["word_id"])
    lookup = op.create_table(
        "learning_state_type",
        sa.Column("code", sa.String(30), primary_key=True),
    )
    op.bulk_insert(lookup, [{"code": c} for c in STATE_TYPES])
    op.create_table(
        "learning_state", _pk(),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("word_id", sa.Integer, sa.ForeignKey("word.id"), nullable=False),
        sa.Column("state_type", sa.String(30), sa.ForeignKey("learning_state_type.code"), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "word_id", "state_type", name="uq_learning_state"),
    )
    op.create_index("ix_learning_state_user_id", "learning_state", ["user_id"])
    op.create_table(
        "learning_state_history", _pk(),
        sa.Column("learning_state_id", sa.Integer, sa.ForeignKey("learning_state.id"), nullable=False),
        sa.Column("event", sa.String(10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event IN ('added','resolved','reopened')", name="ck_history_event"),
    )
    op.create_index("ix_learning_state_history_learning_state_id", "learning_state_history", ["learning_state_id"])
    op.create_table(
        "quiz_attempt", _pk(),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("word_id", sa.Integer, sa.ForeignKey("word.id"), nullable=False),
        sa.Column("discovery_id", sa.Integer, sa.ForeignKey("discovery.id")),
        sa.Column("question_type", sa.String(10), nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("correct", sa.Boolean, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("question_type IN ('de_ko','ko_de','mcq','cloze')", name="ck_quiz_type"),
    )
    op.create_index("ix_quiz_attempt_user_id", "quiz_attempt", ["user_id"])


def downgrade() -> None:
    for t in [
        "quiz_attempt", "learning_state_history", "learning_state", "learning_state_type",
        "discovery", "app_user", "phrase", "word_topic", "token", "word", "sentence", "passage", "topic",
    ]:
        op.drop_table(t)
