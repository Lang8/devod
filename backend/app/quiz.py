"""Rule-based quiz generation and grading. No LLM / NLP dependency: questions are
built purely from the user's discoveries and the shared Word/Sentence data."""
import random
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Discovery, Passage, Sentence, Word, WordTopic

QUESTION_TYPES = ("de_ko", "ko_de", "mcq", "cloze")
BLANK = "_____"
ARTICLE_RE = re.compile(r"^(der|die|das)\s+", re.I)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().casefold())


def _meaning_variants(meaning: str) -> set[str]:
    parts = {norm(meaning)}
    for p in re.split(r"[,;/]", meaning):
        if norm(p):
            parts.add(norm(p))
    return parts


def user_discoveries(session: Session, user_id: int, topic_id: int | None) -> list[Discovery]:
    q = select(Discovery).where(Discovery.user_id == user_id, Discovery.word_id.is_not(None))
    if topic_id is not None:
        in_topic_word = select(WordTopic.word_id).where(WordTopic.topic_id == topic_id)
        in_topic_passage = select(Passage.id).where(Passage.topic_id == topic_id)
        q = q.where(Discovery.word_id.in_(in_topic_word) | Discovery.passage_id.in_(in_topic_passage))
    return list(session.scalars(q.order_by(Discovery.id)))


def _cloze(d: Discovery, sentence: Sentence | None) -> dict | None:
    if sentence is None or not d.surface_form:
        return None
    pat = re.compile(r"(?<!\w)" + re.escape(d.surface_form) + r"(?!\w)")
    if not pat.search(sentence.text_de):
        return None
    return {"prompt": pat.sub(BLANK, sentence.text_de, count=1), "hint": sentence.text_ko}


def _mcq_choices(session: Session, word: Word, vocab: dict[int, Word], rng: random.Random) -> list[str] | None:
    correct = word.meaning_ko
    seen = {norm(correct)}
    pools = [
        [w for w in vocab.values() if w.id != word.id and w.pos == word.pos],
        [w for w in vocab.values() if w.id != word.id],
        list(session.scalars(select(Word).where(Word.id != word.id, Word.pos == word.pos).limit(50))),
    ]
    distractors: list[str] = []
    for pool in pools:
        pool = pool[:]
        rng.shuffle(pool)
        for w in pool:
            if len(distractors) >= 3:
                break
            if norm(w.meaning_ko) not in seen:
                seen.add(norm(w.meaning_ko))
                distractors.append(w.meaning_ko)
    if not distractors:
        return None
    choices = [correct] + distractors
    rng.shuffle(choices)
    return choices


def build_question(session: Session, word: Word, d: Discovery, qtype: str, vocab: dict[int, Word],
                   rng: random.Random) -> dict | None:
    base = {"word_id": word.id, "discovery_id": d.id, "question_type": qtype}
    lemma = d.lemma_override or word.lemma
    if qtype == "de_ko":
        return {**base, "prompt": lemma}
    if qtype == "ko_de":
        return {**base, "prompt": word.meaning_ko}
    if qtype == "mcq":
        choices = _mcq_choices(session, word, vocab, rng)
        return {**base, "prompt": lemma, "choices": choices} if choices else None
    if qtype == "cloze":
        c = _cloze(d, session.get(Sentence, d.sentence_id))
        return {**base, **c} if c else None
    return None


def generate_questions(session: Session, user_id: int, topic_id: int | None, types: list[str],
                       count: int, rng: random.Random | None = None) -> list[dict]:
    rng = rng or random.Random()
    discoveries = user_discoveries(session, user_id, topic_id)
    if not discoveries:
        return []
    all_vocab_ids = set(session.scalars(select(Discovery.word_id).where(
        Discovery.user_id == user_id, Discovery.word_id.is_not(None))))
    vocab = {w.id: w for w in session.scalars(select(Word).where(Word.id.in_(all_vocab_ids)))}
    by_word: dict[int, list[Discovery]] = {}
    for d in discoveries:
        by_word.setdefault(d.word_id, []).append(d)
    out: list[dict] = []
    word_ids = list(by_word)
    while len(out) < count:
        rng.shuffle(word_ids)
        added = False
        for wid in word_ids:
            if len(out) >= count:
                break
            d = rng.choice(by_word[wid])
            for qtype in rng.sample(types, len(types)):
                q = build_question(session, vocab[wid], d, qtype, vocab, rng)
                if q:
                    out.append(q)
                    added = True
                    break
        if not added:
            break
    return out


def grade(word: Word, d: Discovery | None, qtype: str, answer: str) -> tuple[bool, str]:
    """Return (correct, expected)."""
    a = norm(answer)
    if qtype in ("de_ko", "mcq"):
        return (bool(a) and a in _meaning_variants(word.meaning_ko)), word.meaning_ko
    if qtype == "ko_de":
        lemma = d.lemma_override if d and d.lemma_override else word.lemma
        ok = {norm(lemma), norm(ARTICLE_RE.sub("", lemma)), norm(word.lemma)}
        if word.gender and word.pos == "NOUN":
            art = {"m": "der", "f": "die", "n": "das"}.get(word.gender.lower()[:1])
            if art:
                ok.add(norm(f"{art} {word.lemma}"))
        return (bool(a) and (a in ok or norm(ARTICLE_RE.sub("", answer)) in ok)), lemma
    if qtype == "cloze":
        return (bool(a) and d is not None and a == norm(d.surface_form)), (d.surface_form if d else "")
    return False, ""
