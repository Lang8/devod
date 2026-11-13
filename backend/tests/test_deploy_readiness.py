"""Layer separation + deploy-readiness gates for the API package."""
import ast
import pathlib
import re
import tomllib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = {"spacy", "anthropic"}


def test_api_source_never_imports_spacy_or_anthropic():
    offenders = []
    for f in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{f.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert not offenders


def test_api_dependencies_exclude_spacy_and_anthropic():
    proj = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    deps = list(proj["project"]["dependencies"])
    for group in proj.get("dependency-groups", {}).values():
        deps += [d for d in group if isinstance(d, str)]
    declared = {re.split(r"[<>=!~\[ ;]", d, 1)[0].lower().replace("_", "-") for d in deps}
    assert not declared & FORBIDDEN
    lock = tomllib.loads((BACKEND / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"].lower() for p in lock["package"]}
    assert not locked & FORBIDDEN, "transitive spacy/anthropic in API lockfile"


@pytest.fixture
def client(migrated_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    from fastapi.testclient import TestClient

    from app import deps
    from app.main import create_app
    deps.get_engine.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    deps.get_engine.cache_clear()


def test_healthz_returns_200(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["render.yaml", "frontend/vercel.json", ".env.example"])
def test_deploy_files_committed(path):
    assert (BACKEND.parent / path).is_file()


def test_vercel_has_spa_rewrite():
    import json
    cfg = json.loads((BACKEND.parent / "frontend/vercel.json").read_text())
    assert any(r["destination"] == "/index.html" for r in cfg["rewrites"])
