import re

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import quiz, settings
from app.deps import current_user, get_session
from app.models import Discovery, Passage, QuizAttempt, Sentence, Token, Topic, User, Word
from app.security import create_token, hash_password, verify_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid email")
        return v


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DiscoveryIn(BaseModel):
    token_id: int


class DiscoveryPatch(BaseModel):
    lemma_override: str | None = Field(default=None, max_length=200)

    @field_validator("lemma_override")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        v = v.strip() if v else None
        return v or None


class QuizAttemptIn(BaseModel):
    word_id: int
    discovery_id: int | None = None
    question_type: str = Field(pattern="^(de_ko|ko_de|mcq|cloze)$")
    answer: str
    correct: bool


def discovery_out(d: Discovery, session: Session) -> dict:
    word = session.get(Word, d.word_id) if d.word_id else None
    sentence = session.get(Sentence, d.sentence_id)
    passage = session.get(Passage, d.passage_id)
    return {"id": d.id, "word_id": d.word_id, "token_id": d.token_id, "surface_form": d.surface_form,
            "sentence_id": d.sentence_id, "passage_id": d.passage_id,
            "word_lemma": word.lemma if word else None,
            "lemma_override": d.lemma_override,
            "lemma": d.lemma_override or (word.lemma if word else None),
            "sentence_de": sentence.text_de if sentence else None,
            "sentence_ko": sentence.text_ko if sentence else None,
            "passage_title": passage.title if passage else None,
            "created_at": d.created_at.isoformat() if d.created_at else None}


def attempt_out(a: QuizAttempt) -> dict:
    return {"id": a.id, "word_id": a.word_id, "discovery_id": a.discovery_id,
            "question_type": a.question_type, "answer": a.answer, "correct": a.correct}


def word_out(w: Word) -> dict:
    return {"id": w.id, "lemma": w.lemma, "pos": w.pos, "meaning_ko": w.meaning_ko,
            "gender": w.gender, "plural": w.plural}


health = APIRouter(tags=["health"])


@health.get("/healthz")
def healthz(session: Session = Depends(get_session)):
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


auth = APIRouter(prefix="/auth", tags=["auth"])


@auth.post("/register", status_code=201, response_model=TokenOut)
def register(body: Credentials, session: Session = Depends(get_session)):
    if session.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Email already registered")
    return TokenOut(access_token=create_token(user.id))


@auth.post("/login", response_model=TokenOut)
def login(body: Credentials, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return TokenOut(access_token=create_token(user.id))


api = APIRouter(dependencies=[Depends(current_user)])


@api.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email}


@api.get("/topics")
def list_topics(session: Session = Depends(get_session)):
    rows = session.scalars(select(Topic).order_by(Topic.name_de))
    return [{"id": t.id, "slug": t.slug, "name_de": t.name_de, "name_ko": t.name_ko, "level": t.level}
            for t in rows]


@api.get("/topics/{topic_id}/passages")
def list_topic_passages(topic_id: int, session: Session = Depends(get_session)):
    if session.get(Topic, topic_id) is None:
        raise HTTPException(404, "Topic not found")
    rows = session.scalars(select(Passage).where(Passage.topic_id == topic_id).order_by(Passage.id))
    return [{"id": p.id, "topic_id": p.topic_id, "title": p.title, "level": p.level} for p in rows]


@api.get("/passages/{passage_id}")
def get_passage(passage_id: int, session: Session = Depends(get_session)):
    p = session.get(Passage, passage_id)
    if p is None:
        raise HTTPException(404, "Passage not found")
    sentences = session.scalars(
        select(Sentence).where(Sentence.passage_id == p.id).order_by(Sentence.position))
    sentences = list(sentences)
    tokens: dict[int, list[Token]] = {s.id: [] for s in sentences}
    for t in session.scalars(select(Token).where(Token.sentence_id.in_(list(tokens))).order_by(Token.position)):
        tokens[t.sentence_id].append(t)
    return {"id": p.id, "topic_id": p.topic_id, "title": p.title, "level": p.level,
            "sentences": [{"id": s.id, "position": s.position, "text_de": s.text_de, "text_ko": s.text_ko,
                           "tokens": [{"id": t.id, "position": t.position, "surface": t.surface,
                                       "word_id": t.word_id} for t in tokens[s.id]]}
                          for s in sentences]}


@api.post("/discoveries", status_code=201)
def create_discovery(body: DiscoveryIn, user: User = Depends(current_user),
                     session: Session = Depends(get_session)):
    tok = session.get(Token, body.token_id)
    if tok is None:
        raise HTTPException(404, "Token not found")
    if tok.word_id is None:
        raise HTTPException(422, "Token has no resolved word")
    passage_id = session.get(Sentence, tok.sentence_id).passage_id
    d = Discovery(user_id=user.id, word_id=tok.word_id, token_id=tok.id, surface_form=tok.surface,
                  sentence_id=tok.sentence_id, passage_id=passage_id)
    session.add(d)
    session.commit()
    return discovery_out(d, session)


@api.patch("/discoveries/{discovery_id}")
def patch_discovery(discovery_id: int, body: DiscoveryPatch, user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    d = session.scalar(select(Discovery).where(Discovery.id == discovery_id, Discovery.user_id == user.id))
    if d is None:
        raise HTTPException(404, "Discovery not found")
    d.lemma_override = body.lemma_override
    session.commit()
    return discovery_out(d, session)


@api.get("/discoveries")
def list_discoveries(user: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.scalars(select(Discovery).where(Discovery.user_id == user.id).order_by(Discovery.id))
    return [discovery_out(d, session) for d in rows]


@api.get("/discoveries/{discovery_id}")
def get_discovery(discovery_id: int, user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    d = session.scalar(select(Discovery).where(Discovery.id == discovery_id, Discovery.user_id == user.id))
    if d is None:
        raise HTTPException(404, "Discovery not found")
    return discovery_out(d, session)


@api.get("/vocabulary")
def list_vocabulary(user: User = Depends(current_user), session: Session = Depends(get_session)):
    words = session.scalars(
        select(Word).where(Word.id.in_(select(Discovery.word_id).where(Discovery.user_id == user.id)))
        .order_by(Word.lemma))
    return [word_out(w) for w in words]


@api.get("/vocabulary/{word_id}")
def get_vocabulary_entry(word_id: int, user: User = Depends(current_user),
                         session: Session = Depends(get_session)):
    discoveries = list(session.scalars(
        select(Discovery).where(Discovery.user_id == user.id, Discovery.word_id == word_id)
        .order_by(Discovery.id)))
    if not discoveries:
        raise HTTPException(404, "Word not in vocabulary")
    return {**word_out(session.get(Word, word_id)), "discoveries": [discovery_out(d, session) for d in discoveries]}


@api.post("/quiz-attempts", status_code=201)
def create_attempt(body: QuizAttemptIn, user: User = Depends(current_user),
                   session: Session = Depends(get_session)):
    if not session.scalar(select(Discovery.id).where(Discovery.user_id == user.id,
                                                      Discovery.word_id == body.word_id).limit(1)):
        raise HTTPException(404, "Word not in vocabulary")
    if body.discovery_id is not None and not session.scalar(
            select(Discovery.id).where(Discovery.id == body.discovery_id, Discovery.user_id == user.id)):
        raise HTTPException(404, "Discovery not found")
    a = QuizAttempt(user_id=user.id, **body.model_dump())
    session.add(a)
    session.commit()
    return attempt_out(a)


@api.get("/quiz-attempts")
def list_attempts(user: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.scalars(select(QuizAttempt).where(QuizAttempt.user_id == user.id).order_by(QuizAttempt.id))
    return [attempt_out(a) for a in rows]


@api.get("/quiz-attempts/{attempt_id}")
def get_attempt(attempt_id: int, user: User = Depends(current_user),
                session: Session = Depends(get_session)):
    a = session.scalar(select(QuizAttempt).where(QuizAttempt.id == attempt_id, QuizAttempt.user_id == user.id))
    if a is None:
        raise HTTPException(404, "Attempt not found")
    return attempt_out(a)


class QuizAnswerIn(BaseModel):
    word_id: int
    discovery_id: int | None = None
    question_type: str = Field(pattern="^(de_ko|ko_de|mcq|cloze)$")
    answer: str = Field(max_length=500)


@api.get("/quiz/questions")
def quiz_questions(topic_id: int | None = None, types: str = ",".join(quiz.QUESTION_TYPES),
                   count: int = 10, user: User = Depends(current_user),
                   session: Session = Depends(get_session)):
    wanted = [t for t in types.split(",") if t]
    if not wanted or any(t not in quiz.QUESTION_TYPES for t in wanted):
        raise HTTPException(422, "Invalid question types")
    if not 1 <= count <= 50:
        raise HTTPException(422, "count must be 1..50")
    return quiz.generate_questions(session, user.id, topic_id, wanted, count)


@api.post("/quiz/answer", status_code=201)
def quiz_answer(body: QuizAnswerIn, user: User = Depends(current_user),
                session: Session = Depends(get_session)):
    if not session.scalar(select(Discovery.id).where(Discovery.user_id == user.id,
                                                      Discovery.word_id == body.word_id).limit(1)):
        raise HTTPException(404, "Word not in vocabulary")
    d = None
    if body.discovery_id is not None:
        d = session.scalar(select(Discovery).where(Discovery.id == body.discovery_id,
                                                   Discovery.user_id == user.id,
                                                   Discovery.word_id == body.word_id))
        if d is None:
            raise HTTPException(404, "Discovery not found")
    elif body.question_type == "cloze":
        raise HTTPException(422, "cloze requires discovery_id")
    word = session.get(Word, body.word_id)
    correct, expected = quiz.grade(word, d, body.question_type, body.answer)
    a = QuizAttempt(user_id=user.id, word_id=word.id, discovery_id=body.discovery_id,
                    question_type=body.question_type, answer=body.answer, correct=correct)
    session.add(a)
    session.commit()
    return {**attempt_out(a), "expected": expected}


def create_app() -> FastAPI:
    app = FastAPI(title="Deutsch Trainer API")
    origins = settings.cors_origins()
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(health)
    app.include_router(auth)
    app.include_router(api)
    return app


app = create_app()
