"""AC6: every request sends the DeutschTrainerIngest User-Agent and is throttled per host
(1 req/s default, --rate adjustable)."""
import pytest
from click.testing import CliRunner

from deutsch_pipeline.cli import main
from deutsch_pipeline.http import USER_AGENT, FetchError, HttpClient

from .ingest_fakes import (SENTS, FakeLLM, Transport, wiki_body)


def test_throttle_waits_between_same_host_requests():
    sleeps, now = [], [0.0]
    c = HttpClient(transport=Transport([(200, "x")]), rate=1.0, sleep=sleeps.append, clock=lambda: now[0])
    c.get("https://de.wikipedia.org/a")
    c.get("https://de.wikipedia.org/b")
    assert sleeps == [1.0]


def test_throttle_default_is_one_per_second_and_per_host():
    assert HttpClient().min_interval == 1.0
    sleeps, now = [], [0.0]
    c = HttpClient(transport=Transport([(200, "x")]), sleep=sleeps.append, clock=lambda: now[0])
    c.get("https://de.wikipedia.org/a")
    c.get("https://www.gutenberg.org/b")  # different host: no wait
    assert sleeps == []
    now[0] = 0.25
    c.get("https://de.wikipedia.org/c")
    assert sleeps == [0.75]


def test_rate_option_changes_interval_and_sends_user_agent_on_every_request():
    sleeps, now = [], [0.0]
    t = Transport([(200, "x")])
    c = HttpClient(transport=t, rate=4.0, sleep=sleeps.append, clock=lambda: now[0])
    for p in "abc":
        c.get(f"https://de.wikipedia.org/{p}")
    assert sleeps == [0.25, 0.25]
    assert all(call[1]["User-Agent"] == USER_AGENT for call in t.calls)
    assert USER_AGENT.startswith("DeutschTrainerIngest/1.0 (+https://")
    with pytest.raises(ValueError):
        HttpClient(rate=0)


def test_cli_rate_flag_is_passed_to_client(migrated_url, nlp, monkeypatch):
    import deutsch_pipeline.cli as cli
    seen = []
    real = cli.HttpClient
    monkeypatch.setattr(cli, "HttpClient", lambda **kw: seen.append(kw["rate"]) or real(sleep=lambda s: None, **kw))
    base = ["ingest-source", "--kind", "wikipedia", "--ref", "Berlin", "--topic", "stadt", "--level", "A2",
            "--database-url", migrated_url]
    obj = {"transport": Transport([(200, wiki_body(SENTS))]), "llm": FakeLLM(), "nlp": nlp}
    CliRunner().invoke(main, base + ["--rate", "2.5"], obj=obj)
    CliRunner().invoke(main, base, obj=obj)
    assert seen == [2.5, 1.0]


def test_fetch_error_type():
    with pytest.raises(FetchError):
        HttpClient(transport=Transport([(503, "")]), sleep=lambda s: None).get("https://x.org/")
