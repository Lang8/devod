"""Passage generation stage. The LLM client is injected so CI never hits the network."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class GeneratedPassage:
    title: str
    sentences: list[tuple[str, str]]  # (German, Korean translation), in reading order
    model_version: str


class PassageGenerator(Protocol):
    def generate(self, topic_de: str, level: str, n_sentences: int) -> GeneratedPassage: ...


class FixtureGenerator:
    """Replays a recorded passage from a JSON file (deterministic, offline)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def generate(self, topic_de: str, level: str, n_sentences: int) -> GeneratedPassage:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return GeneratedPassage(
            title=data["title"],
            sentences=[(s["de"], s["ko"]) for s in data["sentences"]],
            model_version=data.get("model_version", "fixture"),
        )


class AnthropicGenerator:
    """Real generation via the Anthropic API. The SDK is imported lazily and is
    an optional pipeline-only dependency (never installed in the API server)."""

    def __init__(self, client=None, model: str = "claude-sonnet-5-5"):
        if client is None:
            import anthropic  # noqa: PLC0415

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.client = client
        self.model = model

    def generate(self, topic_de: str, level: str, n_sentences: int) -> GeneratedPassage:
        prompt = (
            f"Schreibe einen zusammenhängenden deutschen Lesetext zum Thema '{topic_de}' "
            f"auf CEFR-Niveau {level} mit genau {n_sentences} Sätzen und übersetze jeden Satz ins Koreanische. "
            'Antworte NUR mit JSON: {"title": str, "sentences": [{"de": str, "ko": str}]}'
        )
        msg = self.client.messages.create(
            model=self.model, max_tokens=2000, messages=[{"role": "user", "content": prompt}]
        )
        data = json.loads(msg.content[0].text)
        return GeneratedPassage(
            title=data["title"],
            sentences=[(s["de"], s["ko"]) for s in data["sentences"]],
            model_version=self.model,
        )
