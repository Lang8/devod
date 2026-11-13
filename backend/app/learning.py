"""State-change service: every change writes a LearningStateHistory row."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LearningState, LearningStateHistory


def set_state(session: Session, user_id: int, word_id: int, state_type: str, active: bool) -> LearningState:
    ls = session.scalar(select(LearningState).where(
        LearningState.user_id == user_id, LearningState.word_id == word_id,
        LearningState.state_type == state_type))
    now = dt.datetime.now(dt.timezone.utc)
    if ls is None:
        ls = LearningState(user_id=user_id, word_id=word_id, state_type=state_type, active=active,
                           resolved_at=None if active else now)
        session.add(ls)
        session.flush()
        session.add(LearningStateHistory(learning_state_id=ls.id, event="added" if active else "resolved"))
    elif ls.active != active:
        ls.active = active
        ls.resolved_at = None if active else now
        session.add(LearningStateHistory(learning_state_id=ls.id, event="reopened" if active else "resolved"))
    session.flush()
    return ls
