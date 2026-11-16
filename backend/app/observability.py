"""Sentry error tracking. Entirely off (no-op) when no DSN is configured."""
import os


def init_sentry(dsn: str | None) -> bool:
    """Initialise Sentry if a DSN is given. Returns True when enabled."""
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=0.0,
    )
    return True
