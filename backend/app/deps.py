from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import settings
from app.models import User
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_engine():
    return create_engine(settings.database_url(), pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    unauth = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauth
    uid = decode_token(creds.credentials)
    user = session.get(User, uid) if uid is not None else None
    if user is None:
        raise unauth
    return user
