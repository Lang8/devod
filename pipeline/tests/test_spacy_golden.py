"""spaCy-only golden cases: surface form in context -> lemma, against the pinned model."""
import pytest
import spacy

PINNED_MODEL = "de_core_news_md"
PINNED_MODEL_VERSION = "3.8.0"

# (sentence, surface, expected lemma)
GOLDEN = [
    ("Er hat den Streit vermieden.", "vermieden", "vermeiden"),
    ("Sie trägt einen roten Mantel.", "trägt", "tragen"),
    ("Wir sind nach Hause gegangen.", "gegangen", "gehen"),
    ("Er hat einen Brief geschrieben.", "geschrieben", "schreiben"),
]


@pytest.fixture(scope="module")
def nlp():
    model = spacy.load(PINNED_MODEL)
    assert model.meta["version"] == PINNED_MODEL_VERSION
    return model


@pytest.mark.parametrize("sentence,surface,lemma", GOLDEN)
def test_surface_lemma_in_context(nlp, sentence, surface, lemma):
    tokens = [t for t in nlp(sentence) if t.text == surface]
    assert len(tokens) == 1
    assert tokens[0].lemma_ == lemma
    assert tokens[0].pos_ == "VERB"
