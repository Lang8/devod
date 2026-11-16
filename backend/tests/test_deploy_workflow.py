"""Structure checks for .github/workflows/deploy.yml (text-based; no YAML dependency)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
WF = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")


def job_block(name):
    m = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", WF, re.S | re.M)
    assert m, f"job {name} missing"
    return m.group(1)


def test_triggers_on_green_ci_for_main():
    assert re.search(r"workflow_run:\s+workflows: \[CI\]\s+types: \[completed\]\s+branches: \[main\]", WF)
    assert "workflow_run.conclusion == 'success'" in job_block("deploy")


def test_job_order_is_deploy_smoke_e2e_rollback():
    assert "needs: deploy" in job_block("smoke")
    assert "smoke" in re.search(r"needs: (.*)", job_block("e2e")).group(1)
    rb = re.search(r"needs: (.*)", job_block("rollback")).group(1)
    assert all(j in rb for j in ("deploy", "smoke", "e2e"))


def test_rollback_triggers_on_failures_and_runs_script():
    rb = job_block("rollback")
    for j in ("deploy", "smoke", "e2e"):
        assert f"needs.{j}.result == 'failure'" in rb
    assert "ops.py rollback" in rb and "always()" in rb


def test_jobs_run_scripts_and_prod_spec():
    assert "ops.py deploy" in job_block("deploy")
    assert "ops.py smoke" in job_block("smoke")
    assert "prod-smoke.spec.js" in job_block("e2e")


def test_secrets_from_github_secrets_and_no_database_url():
    assert "DATABASE_URL" not in WF
    for s in ("RENDER_API_KEY", "RENDER_DEPLOY_HOOK_URL", "VERCEL_TOKEN", "VERCEL_DEPLOY_HOOK_URL",
              "PROD_E2E_EMAIL", "PROD_E2E_PASSWORD"):
        assert f"${{{{ secrets.{s} }}}}" in WF


def test_each_deploy_job_checks_secret_state():
    for j in ("deploy", "smoke", "e2e"):
        b = job_block(j)
        assert "check-secrets" in b and "== 'all_present'" in b


def test_required_secrets_list_excludes_database_url():
    src = (ROOT / "scripts" / "deploy" / "ops.py").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in src.split("REQUIRED_SECRETS = [")[1].split("]")[0]


def test_git_auto_deploy_is_off_for_main():
    import json

    assert re.search(r"^\s+autoDeploy: false$", (ROOT / "render.yaml").read_text(encoding="utf-8"), re.M)
    vercel = json.loads((ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8"))
    assert vercel["git"]["deploymentEnabled"]["main"] is False


def test_ci_runs_pipeline_tests_and_prod_spec():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^  pipeline:\n", ci, re.M)
    assert "PROD_E2E_EMAIL" in ci and "npx playwright test" in ci
