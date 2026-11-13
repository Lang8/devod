import sentry_sdk

from app import observability, settings


def test_no_dsn_is_noop(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert settings.sentry_dsn() is None
    assert observability.init_sentry(settings.sentry_dsn()) is False


def test_blank_dsn_is_noop(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "  ")
    assert settings.sentry_dsn() is None


def test_dsn_initialises_client(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/1")
    try:
        assert observability.init_sentry(settings.sentry_dsn()) is True
        assert sentry_sdk.get_client().dsn == "https://key@o0.ingest.sentry.io/1"
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.init()


def test_app_builds_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    from app.main import create_app

    assert create_app().title == "Deutsch Trainer API"
