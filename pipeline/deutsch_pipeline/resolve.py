"""Resolution layer: separable-verb (svp) merge rule + surface->lemma override table.

Runs on spaCy output; no network, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

# Surface-form overrides for forms the model lemmatizes unreliably (lowercased surface -> lemma).
OVERRIDES: dict[str, str] = {
    "wäre": "sein",
    "wären": "sein",
    "wärst": "sein",
    "wart": "sein",
    "hätte": "haben",
    "hätten": "haben",
    "würde": "werden",
    "würden": "werden",
}


@dataclass(frozen=True)
class ResolvedToken:
    position: int
    surface: str
    lemma: str
    pos: str
    resolved_lemma: str
    separable_head_position: int | None = None  # set on the particle: position of its verb
    separable_particle_position: int | None = None  # set on the verb: position of its particle


def resolve_sentence(nlp, text: str) -> list[ResolvedToken]:
    doc = [t for t in nlp(text) if not t.is_space]
    index = {t.i: n for n, t in enumerate(doc)}
    resolved: dict[int, str] = {}
    head_of: dict[int, int] = {}
    particle_of: dict[int, int] = {}

    for t in doc:
        if t.dep_ == "svp" and t.head.i in index and t.head.pos_ in ("VERB", "AUX"):
            verb_pos, part_pos = index[t.head.i], index[t.i]
            base = t.head.lemma_ or t.head.text
            resolved[verb_pos] = t.text.lower() + base.lower()
            head_of[part_pos] = verb_pos
            particle_of[verb_pos] = part_pos

    out = []
    for n, t in enumerate(doc):
        lemma = t.lemma_ or t.text
        rl = resolved.get(n) or OVERRIDES.get(t.text.lower()) or lemma
        out.append(ResolvedToken(n, t.text, lemma, t.pos_, rl,
                                 head_of.get(n), particle_of.get(n)))
    return out
