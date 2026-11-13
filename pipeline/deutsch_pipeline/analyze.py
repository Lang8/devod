"""spaCy analysis stage: tokens, lemma, POS (pinned German model)."""
from __future__ import annotations

from dataclasses import dataclass

PINNED_MODEL = "de_core_news_md"
PINNED_MODEL_VERSION = "3.8.0"


@dataclass(frozen=True)
class TokenInfo:
    position: int
    surface: str
    lemma: str
    pos: str


def load_nlp():
    import spacy  # noqa: PLC0415

    nlp = spacy.load(PINNED_MODEL)
    if nlp.meta["version"] != PINNED_MODEL_VERSION:
        raise RuntimeError(f"expected {PINNED_MODEL} {PINNED_MODEL_VERSION}, got {nlp.meta['version']}")
    return nlp


def analyze_sentence(nlp, text: str) -> list[TokenInfo]:
    return [
        TokenInfo(position=i, surface=t.text, lemma=t.lemma_ or t.text, pos=t.pos_)
        for i, t in enumerate(t for t in nlp(text) if not t.is_space)
    ]
