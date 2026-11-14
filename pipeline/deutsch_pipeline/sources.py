"""Ingest source adapters. Each adapter declares its license tier and fetches one exact source."""
from __future__ import annotations

import json
import pathlib
import re
import urllib.parse
from dataclasses import dataclass
from typing import Protocol

from .http import HttpClient

OPEN, RESTRICTED = "open", "restricted"


class SourceError(ValueError):
    """The named source is unusable (missing, empty, malformed)."""


@dataclass(frozen=True)
class SourceText:
    url: str
    title: str
    author: str
    license: str
    tier: str
    paragraphs: list[str]
    label_level: str | None = None  # the source's own CEFR label, when it has one
    kind: str = ""


class SourceAdapter(Protocol):
    kind: str
    tier: str

    def fetch(self, client: HttpClient, ref: str, section: str | None = None) -> SourceText: ...


_HEADING = re.compile(r"^\s*=+\s*(.*?)\s*=+\s*$")


def _paragraphs_from_extract(text: str, section: str | None) -> list[str]:
    paras: list[str] = []
    active = section is None
    for block in re.split(r"\n\s*\n|\n(?==)", text.replace("\r", "")):
        block = block.strip()
        if not block:
            continue
        m = _HEADING.match(block)
        if m:
            if section is not None and m.group(1).casefold() == section.casefold():
                active = True
            continue
        if active:
            paras.append(re.sub(r"\s*\n\s*", " ", block))
    return paras


class _MediaWikiSource:
    kind = ""
    tier = OPEN
    host = ""
    license = ""
    author = ""

    def _title(self, ref: str) -> str:
        if ref.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(ref)
            if parsed.hostname != self.host or not parsed.path.startswith("/wiki/"):
                raise SourceError(f"not a {self.host} article URL: {ref}")
            return urllib.parse.unquote(parsed.path[len("/wiki/"):]).replace("_", " ")
        return ref.strip().replace("_", " ")

    def fetch(self, client: HttpClient, ref: str, section: str | None = None) -> SourceText:
        title = self._title(ref)
        if not title:
            raise SourceError("empty article title")
        body = client.get(f"https://{self.host}/w/api.php", {
            "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
            "format": "json", "formatversion": 2, "titles": title})
        try:
            page = json.loads(body)["query"]["pages"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SourceError(f"unexpected API response for {title!r}") from exc
        if page.get("missing"):
            raise SourceError(f"article {title!r} does not exist")
        real_title = page.get("title", title)
        url = f"https://{self.host}/wiki/{urllib.parse.quote(real_title.replace(' ', '_'))}"
        return SourceText(url=url, title=real_title, author=self.author, license=self.license,
                          tier=self.tier, kind=self.kind,
                          paragraphs=_paragraphs_from_extract(page.get("extract") or "", section))


class WikipediaSource(_MediaWikiSource):
    kind, host = "wikipedia", "de.wikipedia.org"
    license, author = "CC BY-SA 4.0", "Wikipedia-Autoren"


class WikinewsSource(_MediaWikiSource):
    kind, host = "wikinews", "de.wikinews.org"
    license, author = "CC BY 2.5", "Wikinews-Autoren"


class GutenbergSource:
    kind, tier = "gutenberg", OPEN
    license = "Public Domain"

    def fetch(self, client: HttpClient, ref: str, section: str | None = None) -> SourceText:
        m = re.search(r"(\d+)\s*$", ref.strip())
        if not m:
            raise SourceError(f"not a Project Gutenberg ID: {ref!r}")
        book = m.group(1)
        raw = client.get(f"https://www.gutenberg.org/cache/epub/{book}/pg{book}.txt").replace("\r", "")
        title = re.search(r"^Title:\s*(.+)$", raw, re.M)
        author = re.search(r"^Author:\s*(.+)$", raw, re.M)
        start = re.search(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", raw, re.S)
        end = re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", raw)
        body = raw[start.end() if start else 0: end.start() if end else len(raw)]
        paras = []
        active = section is None
        for block in re.split(r"\n\s*\n", body):
            block = re.sub(r"\s*\n\s*", " ", block.strip())
            if not block:
                continue
            if not active:
                active = block.casefold() == (section or "").casefold()
                continue
            paras.append(block)
        return SourceText(url=f"https://www.gutenberg.org/ebooks/{book}",
                          title=title.group(1).strip() if title else f"Gutenberg #{book}",
                          author=author.group(1).strip() if author else "Unknown",
                          license=self.license, tier=self.tier, kind=self.kind, paragraphs=paras)


class LocalFileSource:
    """Restricted tier: a file downloaded by hand (e.g. Goethe/ÖSD model test). Never crawls.

    Optional header lines at the top: Title:, Author:, Level:, License:, Section-free body after a blank line.
    """
    kind, tier = "local_file", RESTRICTED
    default_license = "restricted: local file"

    def fetch(self, client: HttpClient, ref: str, section: str | None = None) -> SourceText:
        path = pathlib.Path(ref)
        if not path.is_file():
            raise SourceError(f"local file not found: {ref}")
        raw = path.read_text(encoding="utf-8").replace(CR, "")
        meta: dict[str, str] = {}
        lines = raw.split(NL)
        i = 0
        while i < len(lines):
            m = re.match(r"^(Title|Author|Level|License):\s*(.*)$", lines[i])
            if not m:
                break
            meta[m.group(1).lower()] = m.group(2).strip()
            i += 1
        paras: list[str] = []
        active = section is None
        for block in re.split(PARA_BREAK, NL.join(lines[i:])):
            block = re.sub(LINE_BREAK, " ", block.strip())
            if not block:
                continue
            if not active:
                active = block.casefold() == (section or "").casefold()
                continue
            paras.append(block)
        level = meta.get("level", "").upper() or None
        return SourceText(url=path.resolve().as_uri(), title=meta.get("title") or path.stem,
                          author=meta.get("author") or "Unknown",
                          license=meta.get("license") or self.default_license, tier=self.tier,
                          kind=self.kind, paragraphs=paras, label_level=level)


CR, NL = chr(13), chr(10)
PARA_BREAK = re.compile(NL + r"\s*" + NL)
LINE_BREAK = re.compile(r"\s*" + NL + r"\s*")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_local_db_url(database_url: str) -> bool:
    """True only when the URL's parsed hostname is exactly localhost, 127.0.0.1 or ::1."""
    try:
        host = urllib.parse.urlparse(str(database_url)).hostname
    except ValueError:
        return False
    return host in LOCAL_HOSTS


ADAPTERS = {"wikipedia": WikipediaSource, "wikinews": WikinewsSource, "gutenberg": GutenbergSource,
            "local_file": LocalFileSource}
