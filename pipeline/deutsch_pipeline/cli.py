"""Command: python -m deutsch_pipeline ingest --topic umwelt --level A2"""
from __future__ import annotations

import click
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .analyze import load_nlp
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


if __name__ == "__main__":
    main()
