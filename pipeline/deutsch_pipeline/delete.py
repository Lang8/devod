"""Safe topic deletion: one transaction, dry-run by default, refuses if real-user data references the topic."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Discovery,
    LearningState,
    LearningStateHistory,
    Passage,
    Phrase,
    QuizAttempt,
    Sentence,
    Token,
    Topic,
    User,
    Word,
    WordTopic,
)


class DeleteRefused(Exception):
    """Other users' data still references the topic; nothing was deleted."""


@dataclass
class DeletePlan:
    slug: str
    found: bool = True
    counts: dict[str, int] = field(default_factory=dict)
    blockers: dict[str, int] = field(default_factory=dict)
    applied: bool = False

    def lines(self) -> list[str]:
        return [f"  {k}: {v}" for k, v in self.counts.items()]


def delete_topic(session: Session, slug: str, *, test_account_email: str | None, apply: bool) -> DeletePlan:
    """Plan (and with apply=True execute) deletion of a topic. Caller owns commit/rollback.

    Raises DeleteRefused (before any write) if a non-test user references the topic.
    """
    topic = session.scalar(select(Topic).where(Topic.slug == slug))
    if topic is None:
        return DeletePlan(slug=slug, found=False)

    passage_ids = list(session.scalars(select(Passage.id).where(Passage.topic_id == topic.id)))
    sentence_ids = list(session.scalars(select(Sentence.id).where(Sentence.passage_id.in_(passage_ids)))) if passage_ids else []
    token_ids = list(session.scalars(select(Token.id).where(Token.sentence_id.in_(sentence_ids)))) if sentence_ids else []
    phrase_ids = list(session.scalars(select(Phrase.id).where(Phrase.sentence_id.in_(sentence_ids)))) if sentence_ids else []

    # Candidate words: linked to this topic via WordTopic or referenced by its tokens.
    cand = set(session.scalars(select(WordTopic.word_id).where(WordTopic.topic_id == topic.id)))
    if token_ids:
        cand |= set(session.scalars(select(Token.word_id).where(Token.id.in_(token_ids), Token.word_id.isnot(None))))
    kept_words: set[int] = set()
    if cand:
        kept_words |= set(session.scalars(
            select(WordTopic.word_id).where(WordTopic.word_id.in_(cand), WordTopic.topic_id != topic.id)))
        kept_words |= set(session.scalars(
            select(Token.word_id).where(Token.word_id.in_(cand), Token.id.notin_(token_ids or [-1]))))
    orphan_ids = sorted(cand - kept_words)
    wordtopic_n = session.scalar(select(func.count()).select_from(WordTopic).where(WordTopic.topic_id == topic.id))

    # User-area rows referencing rows that will be deleted.
    disc_conds = [Discovery.passage_id.in_(passage_ids)] if passage_ids else []
    if sentence_ids:
        disc_conds.append(Discovery.sentence_id.in_(sentence_ids))
    if token_ids:
        disc_conds.append(Discovery.token_id.in_(token_ids))
    if phrase_ids:
        disc_conds.append(Discovery.phrase_id.in_(phrase_ids))
    if orphan_ids:
        disc_conds.append(Discovery.word_id.in_(orphan_ids))
    disc_q = or_(*disc_conds) if disc_conds else None

    test_uid = None
    if test_account_email:
        test_uid = session.scalar(select(User.id).where(User.email == test_account_email))

    def other_users(col):
        return col.isnot(None) if test_uid is None else col != test_uid

    blockers: dict[str, int] = {}
    if disc_q is not None:
        n = session.scalar(select(func.count()).select_from(Discovery).where(disc_q, other_users(Discovery.user_id)))
        if n:
            blockers["discovery"] = n
    if orphan_ids:
        n = session.scalar(select(func.count()).select_from(LearningState).where(
            LearningState.word_id.in_(orphan_ids), other_users(LearningState.user_id)))
        if n:
            blockers["learning_state"] = n
    qa_conds = []
    if orphan_ids:
        qa_conds.append(QuizAttempt.word_id.in_(orphan_ids))
    if disc_q is not None:
        qa_conds.append(QuizAttempt.discovery_id.in_(select(Discovery.id).where(disc_q)))
    if qa_conds:
        n = session.scalar(select(func.count()).select_from(QuizAttempt).where(
            or_(*qa_conds), other_users(QuizAttempt.user_id)))
        if n:
            blockers["quiz_attempt"] = n

    # Counts of what would be removed.
    counts: dict[str, int] = {}
    if test_uid is not None:
        t = Discovery.user_id == test_uid
        counts["test_account_discovery"] = (
            session.scalar(select(func.count()).select_from(Discovery).where(disc_q, t)) if disc_q is not None else 0)
        counts["test_account_learning_state"] = (
            session.scalar(select(func.count()).select_from(LearningState).where(
                LearningState.word_id.in_(orphan_ids), LearningState.user_id == test_uid)) if orphan_ids else 0)
        tq = []
        if orphan_ids:
            tq.append(QuizAttempt.word_id.in_(orphan_ids))
        if disc_q is not None:
            tq.append(QuizAttempt.discovery_id.in_(select(Discovery.id).where(disc_q)))
        counts["test_account_quiz_attempt"] = (
            session.scalar(select(func.count()).select_from(QuizAttempt).where(
                or_(*tq), QuizAttempt.user_id == test_uid)) if tq else 0)
    counts.update({
        "phrase": len(phrase_ids),
        "token": len(token_ids),
        "sentence": len(sentence_ids),
        "passage": len(passage_ids),
        "word_topic_links": wordtopic_n,
        "word_orphans": len(orphan_ids),
        "words_kept_unlinked": len(cand & kept_words),
        "topic": 1,
    })
    plan = DeletePlan(slug=slug, counts=counts, blockers=blockers)
    if blockers:
        raise DeleteRefused(
            f"topic {slug!r} is still referenced by other users' data: "
            + ", ".join(f"{k}={v}" for k, v in blockers.items()))
    if not apply:
        return plan

    # --- apply, test-account user data first ---
    if test_uid is not None:
        qa_del = []
        if orphan_ids:
            qa_del.append(QuizAttempt.word_id.in_(orphan_ids))
        if disc_q is not None:
            qa_del.append(QuizAttempt.discovery_id.in_(select(Discovery.id).where(disc_q)))
        if qa_del:
            session.execute(delete(QuizAttempt).where(or_(*qa_del), QuizAttempt.user_id == test_uid))
        if disc_q is not None:
            session.execute(delete(Discovery).where(disc_q, Discovery.user_id == test_uid))
        if orphan_ids:
            ls = select(LearningState.id).where(
                LearningState.word_id.in_(orphan_ids), LearningState.user_id == test_uid)
            session.execute(delete(LearningStateHistory).where(LearningStateHistory.learning_state_id.in_(ls)))
            session.execute(delete(LearningState).where(
                LearningState.word_id.in_(orphan_ids), LearningState.user_id == test_uid))
    if phrase_ids:
        session.execute(delete(Phrase).where(Phrase.id.in_(phrase_ids)))
    if token_ids:
        session.execute(delete(Token).where(Token.id.in_(token_ids)))
    if sentence_ids:
        session.execute(delete(Sentence).where(Sentence.id.in_(sentence_ids)))
    if passage_ids:
        session.execute(delete(Passage).where(Passage.id.in_(passage_ids)))
    session.execute(delete(WordTopic).where(WordTopic.topic_id == topic.id))
    if orphan_ids:
        session.execute(delete(Word).where(Word.id.in_(orphan_ids)))
    session.execute(delete(Topic).where(Topic.id == topic.id))
    plan.applied = True
    return plan
