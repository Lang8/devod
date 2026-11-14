"""Shared offline fakes for ingest tests: fake transport, fake LLM, fixture bodies, CLI helpers."""
import json

from sqlalchemy import func, select

from app.models import Passage
from deutsch_pipeline.analyze import load_nlp
from deutsch_pipeline.http import HttpClient

SENTS = [f"Das ist Satz Nummer {i} über die Stadt." for i in range(1, 13)]


def wiki_body(sentences, title="Berlin"):
    # Short paragraphs, so paragraph-aligned verbatim excerpts fit every level's budget.
    rest = "\n\n".join(" ".join(sentences[i:i + 2]) for i in range(4, len(sentences), 2))
    text = "Einleitung.\n\n" + " ".join(sentences[:4]) + "\n\n" + rest
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


def client_for(transport):
    return HttpClient(transport=transport, sleep=lambda s: None)


def count(session):
    return session.scalar(select(func.count()).select_from(Passage))


def restricted_file(tmp_path):
    f = tmp_path / "goethe_a2.txt"
    f.write_text("Title: Goethe A2 Modelltest\nAuthor: Goethe-Institut\nLevel: A1\n\n"
                 + "\n\n".join(" ".join(SENTS[i:i + 3]) for i in (0, 3, 6, 9)), encoding="utf-8")
    return str(f)


def cli_args(url, *extra, ref="Berlin"):
    return ["ingest-source", "--kind", "wikipedia", "--ref", ref, "--topic", "stadt", "--level", "A2",
            "--database-url", url, *extra]


def cli_obj(*bodies):
    return {"transport": Transport([(200, b) for b in bodies]), "llm": FakeLLM(), "nlp": load_nlp()}


def write_manifest(tmp_path, entries):
    import yaml
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return str(f)


def entry(ref, level="A2"):
    return {"kind": "wikipedia", "ref": ref, "topic": "stadt", "level": level}
