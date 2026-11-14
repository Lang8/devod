"""Excerpt budgets, paragraph boundaries, verbatim vs adapted, and level source - offline."""
import json

import pytest
from sqlalchemy import select

from app.models import Passage
from deutsch_pipeline.analyze import load_nlp
from deutsch_pipeline.http import HttpClient
from deutsch_pipeline.ingest_source import SENTENCE_BUDGET, IngestError, build_passage, excerpt, ingest_source
from deutsch_pipeline.sources import SourceText

from .test_ingest_source import FakeLLM, Transport


def para(prefix, n):
    return " ".join(f"{prefix} Satz {i} steht hier." for i in range(1, n + 1))


def source(paras, label=None, license="CC BY-SA 4.0"):
    return SourceText(url="https://de.wikipedia.org/wiki/X", title="X", author="A", license=license,
                      tier="open", kind="wikipedia", paragraphs=paras, label_level=label)


@pytest.mark.parametrize("level,budget", list(SENTENCE_BUDGET.items()))
def test_budget_per_level_and_paragraph_boundary(level, budget):
    paras = [para("P1", 3), para("P2", 3), para("P3", 3), para("P4", 3), para("P5", 3), para("P6", 3)]
    got = excerpt(paras, budget)
    assert budget - 1 <= len(got) <= budget + 1
    # ends at a paragraph boundary (a multiple of 3 here)
    assert len(got) % 3 == 0
    assert got == excerpt(paras, budget)  # deterministic
    assert got[0].startswith("P1")


def test_single_long_paragraph_cut_at_budget():
    got = excerpt([para("L", 30)], 6)
    assert len(got) == 6


def test_verbatim_when_source_at_or_below_target():
    for label in ("A1", "A2"):
        gen, src_level, adapted = build_passage(source([para("P", 8)], label=label), "A2", FakeLLM("C2"))
        assert adapted is False and src_level == label
        assert gen.sentences[0][0].startswith("P Satz 1")


def test_harder_is_adapted_and_never_upward():
    llm = FakeLLM("A1")  # estimator re-rates the adaptation at A1 <= target
    gen, src_level, adapted = build_passage(source([para("P", 8)], label="C1"), "A2", llm)
    assert adapted is True and src_level == "C1"
    assert gen.sentences[0][0] == "Einfach."
    # easier source with a harder target is never adapted
    _, _, adapted = build_passage(source([para("P", 14)], label="A1"), "C2", FakeLLM("A1"))
    assert adapted is False


def test_adaptation_rated_too_hard_rejected():
    with pytest.raises(IngestError):
        build_passage(source([para("P", 8)], label="C1"), "A2", FakeLLM("C1"))


def test_label_used_when_present_else_estimator():
    llm = FakeLLM("B2")
    _, lvl, adapted = build_passage(source([para("P", 6)], label="A1"), "A2", llm)
    assert lvl == "A1" and adapted is False
    llm = FakeLLM("A1")
    _, lvl, _ = build_passage(source([para("P", 6)], label=None), "A2", llm)
    assert lvl == "A1"  # estimated


def test_adapted_cc_by_sa_stays_cc_by_sa_and_section(session):
    nlp = load_nlp()
    text = "Intro.\n\n== Geschichte ==\n\n" + para("G", 4) + "\n\n" + para("H", 4) + "\n\n== Ende ==\n\nSchluss."
    body = json.dumps({"query": {"pages": [{"title": "X", "extract": text}]}})
    res = ingest_source(session, kind="wikipedia", ref="X", topic="t", level="A2", section="Geschichte",
                        client=HttpClient(transport=Transport([(200, body)]), sleep=lambda s: None),
                        llm=FakeLLM("A1"), nlp=nlp)
    p = session.get(Passage, res.passage_id)
    assert p.license == "CC BY-SA 4.0" and p.adapted is False
    from app.models import Sentence
    first = session.scalars(select(Sentence).where(Sentence.passage_id == p.id).order_by(Sentence.position)).first()
    assert first.text_de.startswith("G Satz 1")


class SeqLLM(FakeLLM):
    def __init__(self, levels):
        super().__init__()
        self.levels = list(levels)

    def estimate_level(self, text):
        return self.levels.pop(0)


def test_adapted_wikipedia_keeps_cc_by_sa(session):
    body = json.dumps({"query": {"pages": [{"title": "X", "extract": para("P", 8)}]}})
    res = ingest_source(session, kind="wikipedia", ref="X", topic="t", level="A2",
                        client=HttpClient(transport=Transport([(200, body)]), sleep=lambda s: None),
                        llm=SeqLLM(["C1", "A2"]), nlp=load_nlp())
    p = session.get(Passage, res.passage_id)
    assert p.adapted is True and p.source_level == "C1" and p.level == "A2"
    assert p.license == "CC BY-SA 4.0" and p.source_url and p.source_title
