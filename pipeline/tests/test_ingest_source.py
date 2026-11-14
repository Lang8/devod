"""Open-source ingest, fully offline: fake transport + fake LLM."""
import json

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Passage, Sentence
from deutsch_pipeline.analyze import load_nlp
from deutsch_pipeline.cli import main
from deutsch_pipeline.http import USER_AGENT, FetchError, HttpClient
from deutsch_pipeline.ingest_source import IngestError, ingest_source

SENTS = [f"Das ist Satz Nummer {i} über die Stadt." for i in range(1, 13)]


def wiki_body(sentences, title="Berlin"):
    text = "Einleitung.\n\n" + " ".join(sentences[:4]) + "\n\n" + " ".join(sentences[4:])
    return json.dumps({"query": {"pages": [{"title": title, "extract": text}]}})


class FakeLLM:
    def __init__(self, level="A1"):
        self.level = level
        self.calls = 0

    def estimate_level(self, text):
        return self.level

    def translate(self, sentences, level):
        self.calls += 1
        return [f"번역 {i}" for i, _ in enumerate(sentences)]

    def adapt(self, text, level, n):
        return [("Einfach.", "간단하다.")] * n


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(scope="module")
def nlp():
    return load_nlp()


def client_for(transport):
    return HttpClient(transport=transport, sleep=lambda s: None)


def count(session):
    return session.scalar(select(func.count()).select_from(Passage))


def test_wikipedia_verbatim_with_attribution(session, nlp):
    t = Transport([(200, wiki_body(SENTS))])
    res = ingest_source(session, kind="wikipedia", ref="Berlin", topic="stadt", level="A2",
                        client=client_for(t), llm=FakeLLM("A1"), nlp=nlp)
    p = session.get(Passage, res.passage_id)
    assert p.source_url == "https://de.wikipedia.org/wiki/Berlin"
    assert (p.source_title, p.license, p.license_tier) == ("Berlin", "CC BY-SA 4.0", "open")
    assert p.author and p.source_level == "A1" and p.level == "A2" and p.adapted is False
    sents = session.scalars(select(Sentence).where(Sentence.passage_id == p.id).order_by(Sentence.position)).all()
    assert 5 <= len(sents) <= 7
    assert sents[0].text_de == "Einleitung." or sents[0].text_de.startswith("Das ist")
    assert all(s.text_de and s.text_ko for s in sents)
    assert t.calls[0][1]["User-Agent"] == USER_AGENT and t.calls[0][2] == 30


def test_wikinews_and_gutenberg(session, nlp):
    body = wiki_body(SENTS, "Nachricht")
    ingest_source(session, kind="wikinews", ref="https://de.wikinews.org/wiki/Nachricht", topic="n",
                  level="A2", client=client_for(Transport([(200, body)])), llm=FakeLLM(), nlp=nlp)
    p = session.scalars(select(Passage)).one()
    assert p.license == "CC BY 2.5" and p.source_url == "https://de.wikinews.org/wiki/Nachricht"

    book = ("Title: Der Test\nAuthor: Anna Autor\n\n*** START OF THE PROJECT GUTENBERG EBOOK DER TEST ***\n\n"
            + "\n\n".join(" ".join(SENTS[i:i + 4]) for i in (0, 4, 8)) + "\n\n*** END OF THE PROJECT GUTENBERG EBOOK ***\nlicense")
    ingest_source(session, kind="gutenberg", ref="1234", topic="g", level="A2",
                  client=client_for(Transport([(200, book)])), llm=FakeLLM(), nlp=nlp)
    g = session.scalars(select(Passage).where(Passage.source == "gutenberg")).one()
    assert (g.source_title, g.author, g.license) == ("Der Test", "Anna Autor", "Public Domain")
    assert g.source_url == "https://www.gutenberg.org/ebooks/1234"


def test_empty_and_short_sources_rejected(session, nlp):
    for sents in ([], SENTS[:3]):
        with pytest.raises(IngestError):
            ingest_source(session, kind="wikipedia", ref="Leer", topic="x", level="A2",
                          client=client_for(Transport([(200, wiki_body(sents))])), llm=FakeLLM(), nlp=nlp)
    assert count(session) == 0


def test_fetch_timeout_three_attempts_nothing_written(session, nlp):
    t = Transport([TimeoutError("timed out")])
    with pytest.raises(IngestError):
        ingest_source(session, kind="wikipedia", ref="Berlin", topic="x", level="A2",
                      client=client_for(t), llm=FakeLLM(), nlp=nlp)
    assert len(t.calls) == 3 and all(c[2] == 30 for c in t.calls)
    assert count(session) == 0


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


def test_cli_rejects_nonzero_and_succeeds(migrated_url, nlp):
    args = ["ingest-source", "--kind", "wikipedia", "--ref", "Berlin", "--topic", "stadt", "--level", "A2",
            "--database-url", migrated_url]
    bad = CliRunner().invoke(main, args, obj={"transport": Transport([(200, wiki_body([]))]),
                                              "llm": FakeLLM(), "nlp": nlp})
    assert bad.exit_code != 0
    ok = CliRunner().invoke(main, args, obj={"transport": Transport([(200, wiki_body(SENTS))]),
                                             "llm": FakeLLM(), "nlp": nlp})
    assert ok.exit_code == 0, ok.output
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        assert count(s) == 1
    engine.dispose()


def test_fetch_error_type():
    with pytest.raises(FetchError):
        HttpClient(transport=Transport([(503, "")]), sleep=lambda s: None).get("https://x.org/")


# ---- restricted tier: local files, --allow-restricted, local DB host only ----
from deutsch_pipeline.sources import is_local_db_url  # noqa: E402


def _restricted_file(tmp_path):
    f = tmp_path / "goethe_a2.txt"
    f.write_text("Title: Goethe A2 Modelltest\nAuthor: Goethe-Institut\nLevel: A1\n\n"
                 + "\n\n".join(" ".join(SENTS[i:i + 4]) for i in (0, 4, 8)), encoding="utf-8")
    return str(f)


@pytest.mark.parametrize("url,expected", [
    ("postgresql://u:p@localhost:5432/db", True),
    ("postgresql://u:p@127.0.0.1/db", True),
    ("postgresql://u:p@[::1]:5432/db", True),
    ("postgresql://u:p@localhost.evil.com/db", False),
    ("postgresql://localhost@evil.com/db", False),
    ("postgresql://u:localhost@db.supabase.co/db", False),
    ("postgresql://u:p@db.example.com/db?host=localhost", False),
    ("postgresql://u:p@127.0.0.1.evil.com/db", False),
    ("postgresql:///db", False),
])
def test_is_local_db_url(url, expected):
    assert is_local_db_url(url) is expected


def test_restricted_requires_flag_and_writes_nothing(session, nlp, tmp_path):
    ref = _restricted_file(tmp_path)
    with pytest.raises(IngestError):
        ingest_source(session, kind="local_file", ref=ref, topic="stadt", level="A2",
                      client=client_for(Transport([(200, "")])), llm=FakeLLM(), nlp=nlp)
    assert count(session) == 0


def test_restricted_refused_for_nonlocal_host(nlp, tmp_path, monkeypatch):
    from sqlalchemy.engine import make_url

    class Bind:
        url = make_url("postgresql://u:p@localhost.evil.com/db")

    class Sess:
        def get_bind(self):
            return Bind()

    with pytest.raises(IngestError, match="local database"):
        ingest_source(Sess(), kind="local_file", ref=_restricted_file(tmp_path), topic="stadt", level="A2",
                      client=client_for(Transport([(200, "")])), llm=FakeLLM(), nlp=nlp,
                      allow_restricted=True)


def test_restricted_allowed_on_local_db(session, nlp, tmp_path):
    res = ingest_source(session, kind="local_file", ref=_restricted_file(tmp_path), topic="stadt", level="A2",
                        client=client_for(Transport([(200, "")])), llm=FakeLLM(), nlp=nlp,
                        allow_restricted=True)
    assert count(session) == 1
    p = session.get(Passage, res.passage_id)
    assert p.license_tier == "restricted" and p.source_title == "Goethe A2 Modelltest"


def test_cli_restricted_flag_and_host(migrated_url, nlp, tmp_path):
    ref = _restricted_file(tmp_path)
    base = ["ingest-source", "--kind", "local_file", "--ref", ref, "--topic", "stadt", "--level", "A2"]
    obj = {"llm": FakeLLM(), "nlp": nlp}
    engine = create_engine(migrated_url)

    def rows():
        with Session(engine) as s:
            return count(s)

    no_flag = CliRunner().invoke(main, base + ["--database-url", migrated_url], obj=obj)
    assert no_flag.exit_code != 0 and rows() == 0
    evil = migrated_url.replace("@localhost", "@localhost.evil.com").replace("@127.0.0.1", "@127.0.0.1.evil.com")
    bad = CliRunner().invoke(main, base + ["--allow-restricted", "--database-url", evil], obj=obj)
    assert bad.exit_code != 0 and rows() == 0
    ok = CliRunner().invoke(main, base + ["--allow-restricted", "--database-url", migrated_url], obj=obj)
    local = is_local_db_url(migrated_url)
    assert (ok.exit_code == 0) == local, ok.output
    assert rows() == (1 if local else 0)
    engine.dispose()


# ---- rerun skip, --force, batch manifest ----
def _args(url, *extra, ref="Berlin"):
    return ["ingest-source", "--kind", "wikipedia", "--ref", ref, "--topic", "stadt", "--level", "A2",
            "--database-url", url, *extra]


def _obj(*bodies):
    return {"transport": Transport([(200, b) for b in bodies]), "llm": FakeLLM(), "nlp": load_nlp()}


def test_rerun_skips_and_force_adds(session, nlp):
    kw = dict(kind="wikipedia", ref="Berlin", topic="stadt", level="A2", llm=FakeLLM(), nlp=nlp)
    first = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])), **kw)
    before = session.scalars(select(Sentence.text_de).where(Sentence.passage_id == first.passage_id)).all()
    again = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])), **kw)
    assert again.skipped and again.passage_id == first.passage_id and count(session) == 1
    assert session.scalars(select(Sentence.text_de).where(Sentence.passage_id == first.passage_id)).all() == before
    other = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])),
                          **{**kw, "level": "B1"})
    assert not other.skipped and count(session) == 2  # different level is not a duplicate
    forced = ingest_source(session, client=client_for(Transport([(200, wiki_body(SENTS))])), force=True, **kw)
    assert not forced.skipped and forced.passage_id != first.passage_id and count(session) == 3
    assert session.get(Passage, first.passage_id) is not None


def test_cli_rerun_skip_and_force(migrated_url, nlp):
    engine = create_engine(migrated_url)

    def rows():
        with Session(engine) as s:
            return count(s)

    assert CliRunner().invoke(main, _args(migrated_url), obj=_obj(wiki_body(SENTS))).exit_code == 0
    r = CliRunner().invoke(main, _args(migrated_url), obj=_obj(wiki_body(SENTS)))
    assert r.exit_code == 0 and "SKIPPED" in r.output and rows() == 1
    r = CliRunner().invoke(main, _args(migrated_url, "--force"), obj=_obj(wiki_body(SENTS)))
    assert r.exit_code == 0 and rows() == 2
    engine.dispose()


def _manifest(tmp_path, entries):
    import yaml
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return str(f)


def _entry(ref, level="A2"):
    return {"kind": "wikipedia", "ref": ref, "topic": "stadt", "level": level}


def test_manifest_skips_existing_isolates_failures_and_exits_nonzero(migrated_url, nlp, tmp_path):
    engine = create_engine(migrated_url)

    def rows():
        with Session(engine) as s:
            return count(s)

    assert CliRunner().invoke(main, _args(migrated_url), obj=_obj(wiki_body(SENTS))).exit_code == 0
    m = _manifest(tmp_path, [_entry("Berlin"), _entry("Leer"), _entry("Hamburg")])
    obj = _obj(wiki_body(SENTS, "Berlin"), wiki_body([], "Leer"), wiki_body(SENTS, "Hamburg"))
    res = CliRunner().invoke(main, ["ingest-manifest", m, "--database-url", migrated_url], obj=obj)
    assert res.exit_code != 0
    assert "SKIPPED" in res.output and "FAILED" in res.output
    assert "1 stored, 1 skipped, 1 failed" in res.output
    assert rows() == 2  # failure neither undid Berlin nor blocked Hamburg
    m2 = _manifest(tmp_path, [_entry("Berlin"), _entry("Hamburg")])
    obj = _obj(wiki_body(SENTS, "Berlin"), wiki_body(SENTS, "Hamburg"))
    res = CliRunner().invoke(main, ["ingest-manifest", m2, "--database-url", migrated_url], obj=obj)
    assert res.exit_code == 0 and "2 skipped" in res.output and rows() == 2
    engine.dispose()


def test_manifest_fetch_failure_does_not_block_batch(migrated_url, nlp, tmp_path):
    m = _manifest(tmp_path, [_entry("Boom"), _entry("Hamburg")])
    obj = {"transport": Transport([TimeoutError("x"), TimeoutError("x"), TimeoutError("x"),
                                   (200, wiki_body(SENTS, "Hamburg"))]),
           "llm": FakeLLM(), "nlp": nlp}
    res = CliRunner().invoke(main, ["ingest-manifest", m, "--database-url", migrated_url], obj=obj)
    assert res.exit_code != 0 and "1 stored" in res.output and "1 failed" in res.output


def test_manifest_restricted_entry_refused_without_flag(migrated_url, nlp, tmp_path):
    m = _manifest(tmp_path, [{"kind": "local_file", "ref": _restricted_file(tmp_path),
                              "topic": "stadt", "level": "A2"}])
    res = CliRunner().invoke(main, ["ingest-manifest", m, "--database-url", migrated_url],
                             obj={"llm": FakeLLM(), "nlp": nlp})
    assert res.exit_code != 0
    engine = create_engine(migrated_url)
    with Session(engine) as s:
        assert count(s) == 0
    engine.dispose()
