"""Runtime config from env vars (DATABASE_URL, JWT_SECRET, CORS_ORIGINS)."""
import os


def database_url() -> str:
    url = os.environ["DATABASE_URL"]
    for p in ("postgresql://", "postgres://"):
        if url.startswith(p):
            return "postgresql+psycopg://" + url[len(p):]
    return url


def jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def cors_origins() -> list[str]:
    return [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]


JWT_ALGORITHM = "HS256"
JWT_TTL_MINUTES = int(os.environ.get("JWT_TTL_MINUTES", "60"))
