"""Command: python -m deutsch_pipeline ingest --topic umwelt --level A2"""
from __future__ import annotations

import click
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .analyze import load_nlp
from .delete import DeleteRefused, delete_topic
from .generate import AnthropicGenerator, FixtureGenerator
from .store import ingest_topic


def normalize_url(url: str) -> str:
    for p in ("postgresql://", "postgres://"):
        if url.startswith(p):
            return "postgresql+psycopg://" + url[len(p):]
    return url


@click.group()
def main() -> None:
    """Offline content pipeline."""


@main.command()
@click.option("--topic", required=True, help="Topic slug, e.g. umwelt")
@click.option("--level", default="A2", show_default=True)
@click.option("--sentences", default=6, show_default=True)
@click.option("--fixture", type=click.Path(exists=True, dir_okay=False),
              help="Replay a recorded passage JSON instead of calling Claude")
@click.option("--database-url", envvar="DATABASE_URL", required=True)
def ingest(topic: str, level: str, sentences: int, fixture: str | None, database_url: str) -> None:
    """Generate (or replay) a passage for TOPIC, analyze it with spaCy and store it."""
    generator = FixtureGenerator(fixture) if fixture else AnthropicGenerator()
    nlp = load_nlp()
    engine = create_engine(normalize_url(database_url))
    with Session(engine) as session:
        passage = ingest_topic(session, topic, level, generator, nlp, n_sentences=sentences)
        click.echo(f"stored passage id={passage.id} topic={topic} title={passage.title!r}")


@main.command()
@click.option("--topic", required=True, help="Topic slug to delete")
@click.option("--database-url", envvar="DATABASE_URL", required=True)
@click.option("--test-account-email", envvar="PROD_TEST_ACCOUNT_EMAIL", default=None,
              help="Production test account whose user data is cleaned first")
@click.option("--yes", is_flag=True, help="Actually delete (default is a dry-run)")
def delete(topic: str, database_url: str, test_account_email: str | None, yes: bool) -> None:
    """Delete TOPIC and its shared-area data (dry-run unless --yes)."""
    engine = create_engine(normalize_url(database_url))
    try:
        with Session(engine) as session:
            try:
                plan = delete_topic(session, topic, test_account_email=test_account_email, apply=yes)
            except DeleteRefused as exc:
                session.rollback()
                click.echo(f"REFUSED: {exc}. Nothing was deleted.", err=True)
                raise SystemExit(1)
            if not plan.found:
                session.rollback()
                click.echo(f"topic {topic!r} not found; nothing to delete")
                return
            if yes:
                session.commit()
                click.echo(f"deleted topic {topic!r}:")
            else:
                session.rollback()
                click.echo(f"DRY-RUN: would delete topic {topic!r} (pass --yes to apply):")
            for line in plan.lines():
                click.echo(line)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
