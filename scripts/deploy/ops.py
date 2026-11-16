"""Deploy / smoke / rollback helpers for the GitHub Actions deploy workflow.

Stdlib only. Every outbound HTTP call has an explicit timeout (default 30s).
Usage: python scripts/deploy/ops.py {check-secrets|deploy|smoke|rollback}
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HTTP_TIMEOUT = 30
SMOKE_ATTEMPTS = 6
SMOKE_INTERVAL = 30
POLL_ATTEMPTS = 40
POLL_INTERVAL = 15

# NOTE: the production DATABASE_URL is deliberately NOT here; CI never holds it.
REQUIRED_SECRETS = [
    "RENDER_API_KEY",
    "RENDER_SERVICE_ID",
    "RENDER_DEPLOY_HOOK_URL",
    "VERCEL_TOKEN",
    "VERCEL_PROJECT_ID",
    "VERCEL_DEPLOY_HOOK_URL",
    "PROD_API_URL",
    "PROD_FRONTEND_URL",
    "PROD_E2E_EMAIL",
    "PROD_E2E_PASSWORD",
]

ROOT_MARKER = 'id="root"'
RENDER_FAILED = ("build_failed", "update_failed", "canceled", "deactivated", "pre_deploy_failed")


class ApiError(RuntimeError):
    pass


def _redact(url: str) -> str:
    # Deploy hook URLs carry their secret in the path/query: never print them.
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}/..."


def http_request(method, url, headers=None, body=None, timeout=HTTP_TIMEOUT):
    """Return (status, parsed_json_or_text). Raises ApiError on network error/timeout/non-2xx."""
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ApiError(f"{method} {_redact(url)} -> HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(f"{method} {_redact(url)} failed: {e}") from e
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, raw


# ---------------------------------------------------------------- secrets
def secrets_state(env) -> tuple[str, list[str]]:
    missing = [k for k in REQUIRED_SECRETS if not (env.get(k) or "").strip()]
    if not missing:
        return "all_present", []
    if len(missing) == len(REQUIRED_SECRETS):
        return "all_missing", missing
    return "partial", missing


def summary(text: str, env=os.environ):
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


def set_output(key: str, value: str, env=os.environ):
    path = env.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def cmd_check_secrets(env=os.environ) -> int:
    state, missing = secrets_state(env)
    set_output("state", state, env)
    job = env.get("JOB_LABEL", "deploy")
    if state == "all_present":
        summary(f"### {job}: required secrets present", env)
        return 0
    if state == "all_missing":
        summary(
            f"### :warning: {job}: **skipped** (not deployed)\n"
            "All deploy secrets are missing, so nothing was deployed or verified. "
            "This is NOT a successful deploy. See docs/runbook.md.", env)
        return 0
    summary(f"### :x: {job}: partial secret configuration\nMissing secrets: {', '.join(missing)}", env)
    print(f"::error::Missing deploy secrets: {', '.join(missing)}", file=sys.stderr)
    return 1


# ------------------------------------------------------------------ helpers
def _render_headers(env):
    return {"Authorization": f"Bearer {env['RENDER_API_KEY']}", "Accept": "application/json"}


def _vercel_headers(env):
    return {"Authorization": f"Bearer {env['VERCEL_TOKEN']}"}


def _vq(env, extra=None):
    q = dict(extra or {})
    if env.get("VERCEL_TEAM_ID"):
        q["teamId"] = env["VERCEL_TEAM_ID"]
    return urllib.parse.urlencode(q)


def render_live_deploy_id(env, req):
    url = f"https://api.render.com/v1/services/{env['RENDER_SERVICE_ID']}/deploys?limit=10"
    _, data = req("GET", url, _render_headers(env), None, timeout=HTTP_TIMEOUT)
    for item in data if isinstance(data, list) else []:
        d = item.get("deploy", item)
        if d.get("status") == "live":
            return d["id"]
    return None


def vercel_ready_deployment_id(env, req):
    q = _vq(env, {"projectId": env["VERCEL_PROJECT_ID"], "target": "production", "state": "READY", "limit": 1})
    _, data = req("GET", f"https://api.vercel.com/v6/deployments?{q}", _vercel_headers(env), None,
                  timeout=HTTP_TIMEOUT)
    deps = data.get("deployments", []) if isinstance(data, dict) else []
    return deps[0]["uid"] if deps else None


# ------------------------------------------------------------------- deploy
def cmd_deploy(env=os.environ, req=None, sleep=time.sleep) -> int:
    req = req or http_request
    state, _ = secrets_state(env)
    if state != "all_present":
        return cmd_check_secrets(env)
    try:
        prev_render = render_live_deploy_id(env, req)
        prev_vercel = vercel_ready_deployment_id(env, req)
    except ApiError as e:
        summary(f"### :x: deploy: could not snapshot previous deploys: {e}", env)
        return 1
    # Persist before triggering so a failed deploy can still be rolled back.
    set_output("render_previous_deploy_id", prev_render or "", env)
    set_output("vercel_previous_deployment_id", prev_vercel or "", env)
    failures = []
    render_id = None
    try:
        _, resp = req("POST", env["RENDER_DEPLOY_HOOK_URL"], {}, None, timeout=HTTP_TIMEOUT)
        if isinstance(resp, dict):
            render_id = (resp.get("deploy") or {}).get("id") or resp.get("id")
    except ApiError as e:
        failures.append(f"Render deploy hook: {e}")
    try:
        req("POST", env["VERCEL_DEPLOY_HOOK_URL"], {}, None, timeout=HTTP_TIMEOUT)
    except ApiError as e:
        failures.append(f"Vercel deploy: {e}")
    if not failures:
        try:
            _wait_render(env, req, sleep, render_id)
            _wait_vercel(env, req, sleep, prev_vercel)
        except ApiError as e:
            failures.append(str(e))
    if failures:
        summary("### :x: deploy failed\n" + "\n".join(f"- {f}" for f in failures), env)
        return 1
    summary(f"### deploy triggered and live\n- Render previous: `{prev_render}`\n"
            f"- Vercel previous: `{prev_vercel}`", env)
    return 0


def _wait_render(env, req, sleep, deploy_id):
    if not deploy_id:
        return
    url = f"https://api.render.com/v1/services/{env['RENDER_SERVICE_ID']}/deploys/{deploy_id}"
    for _ in range(POLL_ATTEMPTS):
        _, d = req("GET", url, _render_headers(env), None, timeout=HTTP_TIMEOUT)
        status = d.get("status") if isinstance(d, dict) else None
        if status == "live":
            return
        if status in RENDER_FAILED:
            raise ApiError(f"Render deploy {deploy_id} ended with status {status}")
        sleep(POLL_INTERVAL)
    raise ApiError(f"Render deploy {deploy_id} not live after polling")


def _wait_vercel(env, req, sleep, previous_id):
    q = _vq(env, {"projectId": env["VERCEL_PROJECT_ID"], "target": "production", "limit": 1})
    url = f"https://api.vercel.com/v6/deployments?{q}"
    for _ in range(POLL_ATTEMPTS):
        _, data = req("GET", url, _vercel_headers(env), None, timeout=HTTP_TIMEOUT)
        deps = data.get("deployments", []) if isinstance(data, dict) else []
        if deps and deps[0].get("uid") != previous_id:
            st = deps[0].get("readyState") or deps[0].get("state")
            if st == "READY":
                return
            if st in ("ERROR", "CANCELED"):
                raise ApiError(f"Vercel deployment {deps[0]['uid']} ended with state {st}")
        sleep(POLL_INTERVAL)
    raise ApiError("Vercel deployment not ready after polling")


# ------------------------------------------------------------------- smoke
def cmd_smoke(env=os.environ, req=None, sleep=time.sleep,
              attempts=SMOKE_ATTEMPTS, interval=SMOKE_INTERVAL) -> int:
    req = req or http_request
    state, _ = secrets_state(env)
    if state != "all_present":
        return cmd_check_secrets(env)
    api = env["PROD_API_URL"].rstrip("/") + "/healthz"
    front = env["PROD_FRONTEND_URL"].rstrip("/") + "/"
    last = ""
    for i in range(1, attempts + 1):
        try:
            s1, _ = req("GET", api, {}, None, timeout=HTTP_TIMEOUT)
            s2, body = req("GET", front, {}, None, timeout=HTTP_TIMEOUT)
            if s1 == 200 and s2 == 200 and ROOT_MARKER in str(body):
                summary(f"### smoke passed (attempt {i}/{attempts})\n- {api} 200\n- {front} 200", env)
                return 0
            last = f"healthz={s1} frontend={s2} root_present={ROOT_MARKER in str(body)}"
        except ApiError as e:
            last = str(e)
        print(f"smoke attempt {i}/{attempts} failed: {last}")
        if i < attempts:
            sleep(interval)
    summary(f"### :x: smoke failed after {attempts} attempts\n{last}", env)
    return 1


# ---------------------------------------------------------------- rollback
def _rollback_render(env, req, prev):
    url = f"https://api.render.com/v1/services/{env['RENDER_SERVICE_ID']}/rollback"
    req("POST", url, _render_headers(env), {"deployId": prev}, timeout=HTTP_TIMEOUT)


def _rollback_vercel(env, req, prev):
    q = _vq(env)
    url = f"https://api.vercel.com/v9/projects/{env['VERCEL_PROJECT_ID']}/rollback/{prev}"
    req("POST", url + (f"?{q}" if q else ""), _vercel_headers(env), None, timeout=HTTP_TIMEOUT)


def cmd_rollback(env=os.environ, req=None) -> int:
    """Roll back Render and Vercel independently; report partial failure."""
    req = req or http_request
    targets = {
        "Render": (env.get("RENDER_PREVIOUS_DEPLOY_ID"), _rollback_render),
        "Vercel": (env.get("VERCEL_PREVIOUS_DEPLOYMENT_ID"), _rollback_vercel),
    }
    results = {}
    for name, (prev, fn) in targets.items():
        if not prev:
            results[name] = "NOT rolled back: no previous healthy deploy id recorded"
            continue
        try:
            fn(env, req, prev)
            results[name] = f"rolled back to `{prev}`"
        except (ApiError, KeyError) as e:
            results[name] = f"NOT rolled back: {e}"
    ok = [n for n, r in results.items() if r.startswith("rolled back")]
    bad = [n for n in results if n not in ok]
    head = "### :rotating_light: rollback " + ("complete" if not bad else "PARTIAL FAILURE" if ok else "FAILED")
    lines = "\n".join(f"- {n}: {r}" for n, r in results.items())
    summary(f"{head}\n{lines}\nDB migrations are never rolled back automatically (see docs/runbook.md).", env)
    return 1 if bad else 0


COMMANDS = {"check-secrets": cmd_check_secrets, "deploy": cmd_deploy, "smoke": cmd_smoke, "rollback": cmd_rollback}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(f"usage: ops.py {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]]()


if __name__ == "__main__":
    sys.exit(main())
