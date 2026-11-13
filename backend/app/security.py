import datetime as dt

import bcrypt
import jwt

from app import settings


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + dt.timedelta(minutes=settings.JWT_TTL_MINUTES)}
    return jwt.encode(payload, settings.jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, settings.jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
        return int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
