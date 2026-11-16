"""Deploy/smoke/rollback script tests against mocked Render/Vercel HTTP APIs."""
import importlib.util
import pathlib
import urllib.error

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "deploy" / "ops.py"
spec = importlib.util.spec_from_file_location("deploy_ops", SRC)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

ENV = {k: f"v-{k}" for k in ops.REQUIRED_SECRETS}
ENV.update(PROD_API_URL="https://api.test", PROD_FRONTEND_URL="https://web.test",
           RENDER_DEPLOY_HOOK_URL="https://hook.render/x", VERCEL_DEPLOY_HOOK_URL="https://hook.vercel/y")


class Fake:
    """Routes (method, url-substring) -> response or exception (first match wins); records calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls.append((method, url, body, timeout))
        for (m, frag), resp in self.routes:
            if m == method and frag in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unrouted {method} {url}")


def test_secrets_states():
    assert ops.secrets_state(ENV)[0] == "all_present"
    assert ops.secrets_state({})[0] == "all_missing"
    st, missing = ops.secrets_state({"RENDER_API_KEY": "x"})
    assert st == "partial" and "VERCEL_TOKEN" in missing and "RENDER_API_KEY" not in missing
    assert "DATABASE_URL" not in ops.REQUIRED_SECRETS


def test_check_secrets_outputs(tmp_path):
    summ, out = tmp_path / "s", tmp_path / "o"
    base = {"GITHUB_STEP_SUMMARY": str(summ), "GITHUB_OUTPUT": str(out)}
    assert ops.cmd_check_secrets(base) == 0
    assert "state=all_missing" in out.read_text()
    assert "skipped" in summ.read_text() and "NOT a successful deploy" in summ.read_text()
    summ.write_text("")
    assert ops.cmd_check_secrets({**base, "VERCEL_TOKEN": "t"}) == 1
    assert "RENDER_API_KEY" in summ.read_text()
    assert ops.cmd_check_secrets({**ENV, **base}) == 0


def test_http_request_passes_timeout_and_redacts(monkeypatch):
    seen = {}

    def boom(req, timeout=None):
        seen["timeout"] = timeout
        raise TimeoutError("slow")

    monkeypatch.setattr(ops.urllib.request, "urlopen", boom)
    with pytest.raises(ops.ApiError) as e:
        ops.http_request("GET", "https://x.test/hook/secret")
    assert seen["timeout"] == 30 and "secret" not in str(e.value)

    def http500(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)

    monkeypatch.setattr(ops.urllib.request, "urlopen", http500)
    with pytest.raises(ops.ApiError) as e:
        ops.http_request("POST", "https://x.test/hook/secret")
    assert "500" in str(e.value) and "secret" not in str(e.value)


def _routes(render_status="live", render_hook=None):
    return [
        (("GET", "/deploys?limit=10"), (200, [{"deploy": {"id": "dep-old", "status": "live"}}])),
        (("GET", "/deploys/dep-new"), (200, {"status": render_status})),
        (("GET", "state=READY"), (200, {"deployments": [{"uid": "vc-old"}]})),
        (("GET", "v6/deployments?"), (200, {"deployments": [{"uid": "vc-new", "readyState": "READY"}]})),
        (("POST", "hook.render"), render_hook or (200, {"deploy": {"id": "dep-new"}})),
        (("POST", "hook.vercel"), (200, {})),
    ]


def test_deploy_success_records_previous(tmp_path):
    out = tmp_path / "o"
    f = Fake(_routes())
    assert ops.cmd_deploy({**ENV, "GITHUB_OUTPUT": str(out)}, f, lambda s: None) == 0
    text = out.read_text()
    assert "render_previous_deploy_id=dep-old" in text and "vercel_previous_deployment_id=vc-old" in text
    assert all(c[3] == 30 for c in f.calls)


def test_deploy_hook_timeout_fails_but_records_previous(tmp_path):
    out = tmp_path / "o"
    f = Fake(_routes(render_hook=ops.ApiError("timeout")))
    assert ops.cmd_deploy({**ENV, "GITHUB_OUTPUT": str(out)}, f, lambda s: None) == 1
    assert "render_previous_deploy_id=dep-old" in out.read_text()
    assert any("hook.vercel" in c[1] for c in f.calls)  # other target still triggered


def test_deploy_render_build_failed():
    assert ops.cmd_deploy(ENV, Fake(_routes(render_status="build_failed")), lambda s: None) == 1


def test_deploy_skips_or_fails_on_secrets(tmp_path):
    f = Fake([])
    assert ops.cmd_deploy({"GITHUB_OUTPUT": str(tmp_path / "o")}, f) == 0
    assert ops.cmd_deploy({"VERCEL_TOKEN": "x"}, f) == 1
    assert f.calls == []


def test_smoke_retries_for_cold_start():
    health = iter([ops.ApiError("timeout"), (503, ""), (200, {"status": "ok"})])

    def req(method, url, headers=None, body=None, timeout=None):
        assert timeout == 30
        if "healthz" in url:
            r = next(health)
            if isinstance(r, Exception):
                raise r
            return r
        return 200, '<html><div id="root"></div></html>'

    sleeps = []
    assert ops.cmd_smoke(ENV, req, sleeps.append) == 0
    assert sleeps == [30, 30]


def test_smoke_fails_after_six_attempts():
    sleeps = []
    f = Fake([(("GET", "healthz"), (503, "")), (("GET", "web.test"), (200, "<div id=\"root\">"))])
    assert ops.cmd_smoke(ENV, f, sleeps.append) == 1
    assert len([c for c in f.calls if "healthz" in c[1]]) == 6 and len(sleeps) == 5


def test_smoke_requires_frontend_root():
    f = Fake([(("GET", "healthz"), (200, {})), (("GET", "web.test"), (200, "<html>error</html>"))])
    assert ops.cmd_smoke(ENV, f, lambda s: None, attempts=2) == 1


def _rb_env(tmp_path):
    return {**ENV, "RENDER_PREVIOUS_DEPLOY_ID": "dep-old", "VERCEL_PREVIOUS_DEPLOYMENT_ID": "vc-old",
            "GITHUB_STEP_SUMMARY": str(tmp_path / "s")}


def test_rollback_both(tmp_path):
    f = Fake([(("POST", "render.com"), (200, {})), (("POST", "vercel.com"), (200, {}))])
    assert ops.cmd_rollback(_rb_env(tmp_path), f) == 0
    assert f.calls[0][2] == {"deployId": "dep-old"} and "/rollback/vc-old" in f.calls[1][1]
    assert "complete" in (tmp_path / "s").read_text()


def test_rollback_partial_failure_still_attempts_other(tmp_path):
    f = Fake([(("POST", "render.com"), ops.ApiError("timeout")), (("POST", "vercel.com"), (200, {}))])
    assert ops.cmd_rollback(_rb_env(tmp_path), f) == 1
    assert len(f.calls) == 2
    s = (tmp_path / "s").read_text()
    assert "PARTIAL FAILURE" in s and "Render: NOT rolled back" in s and "Vercel: rolled back" in s


def test_rollback_vercel_fails_render_ok(tmp_path):
    f = Fake([(("POST", "render.com"), (200, {})), (("POST", "vercel.com"), ops.ApiError("HTTP 500"))])
    assert ops.cmd_rollback(_rb_env(tmp_path), f) == 1
    assert "Render: rolled back" in (tmp_path / "s").read_text()


def test_rollback_no_previous_id(tmp_path):
    env = {**_rb_env(tmp_path), "RENDER_PREVIOUS_DEPLOY_ID": ""}
    f = Fake([(("POST", "vercel.com"), (200, {}))])
    assert ops.cmd_rollback(env, f) == 1 and len(f.calls) == 1
