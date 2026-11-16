"""Command: python -m deutsch_pipeline ingest --topic umwelt --level A2"""
from __future__ import annotations

import click
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .analyze import load_nlp
from .delete import DeleteRefused, delete_topic
from .generate import AnthropicGenerator, FixtureGenerator
from .http import HttpClient
from .ingest_source import AnthropicIngestLLM, IngestError, ingest_source
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


@main.command("ingest-source")
@click.option("--kind", type=click.Choice(["wikipedia", "wikinews", "gutenberg", "local_file"]), required=True)
@click.option("--ref", required=True, help="Article title/URL or Gutenberg ID")
@click.option("--topic", required=True)
@click.option("--level", required=True, type=click.Choice(["A1", "A2", "B1", "B2", "C1", "C2"]))
@click.option("--section", default=None, help="Heading where the excerpt starts")
@click.option("--allow-restricted", is_flag=True, help="Permit restricted sources; local DB host only")
@click.option("--force", is_flag=True, help="Add another passage even if (source_url, level) already exists")
@click.option("--rate", default=1.0, show_default=True, help="Max requests per second per host")
@click.option("--database-url", envvar="DATABASE_URL", required=True)
def ingest_source_cmd(kind, ref, topic, level, section, allow_restricted, force, rate, database_url) -> None:
    """Ingest one named open-source text as a passage (exits non-zero, writing nothing, on failure)."""
    obj = click.get_current_context().obj or {}  # tests inject transport / llm / nlp
    client = HttpClient(transport=obj.get("transport"), rate=rate)
    llm = obj.get("llm") or AnthropicIngestLLM()
    nlp = obj.get("nlp") or load_nlp()
    engine = create_engine(normalize_url(database_url))
    try:
        with Session(engine) as session:
            try:
                res = ingest_source(session, kind=kind, ref=ref, topic=topic, level=level, client=client,
                                    llm=llm, nlp=nlp, section=section,
                                    allow_restricted=allow_restricted, force=force)
            except IngestError as exc:
                click.echo(f"REJECTED: {exc}. Nothing was written.", err=True)
                raise SystemExit(1)
            if res.skipped:
                click.echo(f"SKIPPED: passage id={res.passage_id} already exists for this source and level")
                return
            click.echo(f"stored passage id={res.passage_id} title={res.title!r} "
                       f"source_level={res.source_level} adapted={res.adapted}")
    finally:
        engine.dispose()


def load_manifest(path: str) -> list[dict]:
    import yaml  # noqa: PLC0415

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, list):
        raise click.ClickException("manifest must be a YAML list of entries")
    for i, e in enumerate(data):
        if not isinstance(e, dict) or not {"kind", "ref", "topic", "level"} <= e.keys():
            raise click.ClickException(f"manifest entry {i} needs kind, ref, topic and level")
    return data


@main.command("ingest-manifest")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--allow-restricted", is_flag=True, help="Permit restricted sources; local DB host only")
@click.option("--force", is_flag=True, help="Add passages even if (source_url, level) already exists")
@click.option("--rate", default=1.0, show_default=True, help="Max requests per second per host")
@click.option("--database-url", envvar="DATABASE_URL", required=True)
def ingest_manifest_cmd(manifest, allow_restricted, force, rate, database_url) -> None:
    """Run every entry of a YAML manifest; each entry has its own transaction.

    A failing entry is logged and the batch continues; exit is non-zero if any entry failed."""
    entries = load_manifest(manifest)
    obj = click.get_current_context().obj or {}
    client = HttpClient(transport=obj.get("transport"), rate=rate)
    llm = obj.get("llm") or AnthropicIngestLLM()
    nlp = obj.get("nlp") or load_nlp()
    engine = create_engine(normalize_url(database_url))
    stored = skipped = failed = 0
    try:
        for e in entries:
            label = f"{e['kind']}:{e['ref']}@{e['level']}"
            try:
                with Session(engine) as session:
                    res = ingest_source(session, kind=e["kind"], ref=str(e["ref"]), topic=e["topic"],
                                        level=e["level"], client=client, llm=llm, nlp=nlp,
                                        section=e.get("section"), allow_restricted=allow_restricted,
                                        force=force)
            except Exception as exc:  # one bad entry must not stop the batch
                failed += 1
                click.echo(f"FAILED {label}: {exc}", err=True)
                continue
            if res.skipped:
                skipped += 1
                click.echo(f"SKIPPED {label}: passage id={res.passage_id} exists")
            else:
                stored += 1
                click.echo(f"stored {label}: passage id={res.passage_id}")
    finally:
        engine.dispose()
    click.echo(f"batch done: {stored} stored, {skipped} skipped, {failed} failed")
    if failed:
        raise SystemExit(1)


@main.command("verify-publish")
@click.option("--database-url", envvar="DATABASE_URL", required=True)
def verify_publish_cmd(database_url: str) -> None:
    """Read-only: report publish counts; exit non-zero unless 12 open (2 per level), 0 restricted."""
    from .verify_publish import verify_publish  # noqa: PLC0415

    engine = create_engine(normalize_url(database_url))
    try:
        with Session(engine) as session:
            rep = verify_publish(session)
            session.rollback()
    finally:
        engine.dispose()
    for line in rep.lines():
        click.echo(line, err=not rep.ok)
    if not rep.ok:
        raise SystemExit(1)


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
