"""Resolution-layer golden cases (offline, pinned spaCy model, no Anthropic)."""
import pytest

from deutsch_pipeline.analyze import load_nlp
from deutsch_pipeline.resolve import resolve_sentence


@pytest.fixture(scope="module")
def nlp():
    return load_nlp()


def by_surface(tokens, surface):
    found = [t for t in tokens if t.surface == surface]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("sentence", [
    "Er gibt das Buch morgen zurück.",
    "Sie gibt den Schlüssel zurück.",
])
def test_gibt_zurueck_merges_to_zurueckgeben(nlp, sentence):
    toks = resolve_sentence(nlp, sentence)
    gibt, zurueck = by_surface(toks, "gibt"), by_surface(toks, "zurück")
    assert gibt.resolved_lemma == "zurückgeben"
    assert gibt.separable_particle_position == zurueck.position
    assert zurueck.separable_head_position == gibt.position


def test_waere_resolves_to_sein(nlp):
    toks = resolve_sentence(nlp, "Es wäre schön.")
    assert by_surface(toks, "wäre").resolved_lemma == "sein"


def test_non_separable_unchanged(nlp):
    toks = resolve_sentence(nlp, "Er hat einen Brief geschrieben.")
    assert by_surface(toks, "geschrieben").resolved_lemma == "schreiben"
