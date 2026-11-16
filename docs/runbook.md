# Deutsch Trainer — Production Runbook

Free-tier stack: **Render** (FastAPI backend, Docker), **Vercel** (React/Vite SPA), **Neon** (Postgres).
A push to `main` runs CI; when CI is green, `.github/workflows/deploy.yml` triggers the Render deploy hook and the
Vercel deploy, runs smoke checks, runs a production Playwright E2E, and rolls back automatically on failure.
Monthly cost: $0. Render's free web service cold-starts (about 1 minute), which the smoke checks tolerate.

All alerts (Sentry, uptime, rollback, failed workflow) go only to the owner's email.

## Account setup

Account creation and secret entry are manual. Do these once, in this order.

1. **Neon** (neon.tech, free): create a project and database.
   - Copy the **direct** (non-pooled) connection string from the dashboard (host without `-pooler`).
   - Use the direct URL as `DATABASE_URL` on Render. Alembic migrations run at container start
     (`backend/docker-entrypoint.sh` runs `alembic upgrade head`) and must not go through the pooler.
   - Use the same direct URL locally for `pg_dump` and for `deutsch_pipeline` commands.
2. **Render** (render.com, free): New -> Blueprint from this repo (`render.yaml`), service `deutsch-trainer-api`.
   - Set `DATABASE_URL` (Neon direct URL) and `CORS_ORIGINS` (your Vercel URL, e.g. `https://<project>.vercel.app`). `JWT_SECRET` is generated.
   - Optional: `SENTRY_DSN` (backend DSN) and `SENTRY_ENVIRONMENT`.
   - Auto-Deploy is off (`autoDeploy: false` in `render.yaml`); confirm it shows as off in Settings -> Build & Deploy.
     GitHub Actions is the only deploy path for main.
   - Copy the **Deploy Hook URL** (Settings), the **Service ID** (`srv-...`, visible in the dashboard URL) and create an **API key** (Account Settings -> API Keys).
3. **Vercel** (vercel.com, free): import the repo with Root Directory `frontend`.
   - Add env vars `VITE_API_BASE_URL` (the Render URL) and, if used, `VITE_SENTRY_DSN` (frontend DSN).
   - Git auto-deploy for main is turned off by `frontend/vercel.json` (`git.deploymentEnabled.main: false`).
     Do **not** use an Ignored Build Step of `exit 0`: it would also cancel the builds started by the deploy hook.
     After setup, trigger the deploy hook once by hand and confirm it produces a production deployment.
   - Create a **Deploy Hook** (Settings -> Git -> Deploy Hooks, branch `main`). Note the **Project ID** (Settings -> General) and the **Team ID** if the project is under a team. Create an **access token** (Account Settings -> Tokens).
4. **Sentry** (sentry.io, free): create two projects, Python/FastAPI (backend) and React (frontend), and copy each DSN.
   Make sure alert notifications go to the owner's email only.
5. **Uptime monitor** (UptimeRobot or Better Stack, free): configure as described in [Monitoring and alerts](#monitoring-and-alerts).

## GitHub Secrets

Add these under Repo -> Settings -> Secrets and variables -> Actions. The deploy workflow reads them:

| Secret | Value |
| --- | --- |
| `RENDER_API_KEY` | Render API key |
| `RENDER_SERVICE_ID` | Render service id (`srv-...`) |
| `RENDER_DEPLOY_HOOK_URL` | Render deploy hook URL |
| `VERCEL_TOKEN` | Vercel access token |
| `VERCEL_PROJECT_ID` | Vercel project id |
| `VERCEL_TEAM_ID` | Vercel team id (only if the project is in a team; optional) |
| `VERCEL_DEPLOY_HOOK_URL` | Vercel deploy hook URL |
| `PROD_API_URL` | Backend base URL, e.g. `https://deutsch-trainer-api.onrender.com` |
| `PROD_FRONTEND_URL` | Frontend URL, e.g. `https://<project>.vercel.app` |
| `PROD_E2E_EMAIL` | Production test account email |
| `PROD_E2E_PASSWORD` | Production test account password |

Notes:
- **Never** store the production `DATABASE_URL` in GitHub Secrets. CI does not hold it; it lives only in Render's env and on your machine.
- The Neon **direct (non-pooled)** URL is the one used for migrations (Render `DATABASE_URL`).
- Sentry DSNs are set in the Render/Vercel environment; the deploy workflow does not need them.
- Secret states: **all missing** -> the deploy, smoke and E2E jobs write a warning to the job summary and show as *skipped* (CI stays green; this is not a successful deploy).
  **Partially set** -> the deploy job fails and lists the missing secret names. **All set** -> full deploy.

## Test account

The production E2E logs in with a fixed account (no signup in CI). Create it once, by hand, after the first successful deploy:

```bash
curl -X POST "$PROD_API_URL/auth/register" -H "Content-Type: application/json" \
  -d '{"email":"e2e@example.com","password":"CHOOSE-A-STRONG-PASSWORD"}'
```

The first request may take about a minute on a cold start. Store the email and password in the `PROD_E2E_EMAIL` and
`PROD_E2E_PASSWORD` GitHub Secrets. Export the same email as `PROD_TEST_ACCOUNT_EMAIL` on your machine when running `delete --topic`.
The E2E also needs at least one ingested passage (see [Backup and restore](#backup-and-restore)).
The account's data builds up across E2E runs and is cleaned only by `delete --topic`.

## Monitoring and alerts

- **Logs**: Render service logs and Vercel deployment logs (default platform logs).
- **Health**: `GET <PROD_API_URL>/healthz` returns 200.
- **Uptime monitor** (UptimeRobot or Better Stack free tier): monitor `<PROD_API_URL>/healthz` and `<PROD_FRONTEND_URL>`
  with a **5-minute check interval**. The alert contact is the owner's email only. A 5-minute ping also keeps the free Render service from idling for long.
- **Sentry**: backend (`SENTRY_DSN`) and frontend (`VITE_SENTRY_DSN`) report errors; with no DSN set, Sentry is off. Alerts go to the owner's email only.
- **Workflow failures**: GitHub emails the owner when the Deploy workflow fails (this includes runs that were rolled back).
- **Sentry test event (manual check, once after setup)**:
  - Backend: from `backend/` run
    `uv run python -c "import sentry_sdk; sentry_sdk.init(dsn='<BACKEND_DSN>'); sentry_sdk.capture_message('backend sentry test')"`
    then confirm the event appears in the backend Sentry project and the alert email arrives.
  - Frontend: open the production site, run `setTimeout(() => { throw new Error('frontend sentry test') })` in the browser console,
    then confirm the event in the frontend Sentry project.

## Backup and restore

Take a manual `pg_dump` **before each ingest** (and before any `delete --topic --yes`). Use the **direct** Neon URL.

```bash
# Backup (custom format)
pg_dump "$DATABASE_URL" --format=custom --no-owner --file="backup-$(date +%Y%m%d-%H%M).dump"

# Then ingest (manual and local; loads straight into production with no review step)
python -m deutsch_pipeline ingest --topic umwelt --level A2 --database-url "$DATABASE_URL"
```

**Full restore** (replaces the database contents with the dump):

```bash
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" backup-YYYYMMDD-HHMM.dump
```

A restore discards everything written since the dump was taken, including user progress, so use it only when needed.
If the dump predates a schema migration, redeploy afterwards so `alembic upgrade head` runs again at container start.
Run the pipeline and these commands from your own machine, never from CI.

## Deleting a topic

`delete --topic` removes a topic's shared content (passage, sentence, token, phrase, WordTopic). Words and Phrases still linked to
another topic are kept and only unlinked; orphaned ones are deleted. It first cleans the test account's Discovery, LearningState and
QuizAttempt rows. If any **other** user's data still references the topic, it **refuses and deletes nothing**.
It runs in a single transaction and is idempotent.

1. Back up first (see above).
2. **Dry-run** (the default; changes nothing and prints what would be deleted):
   ```bash
   export PROD_TEST_ACCOUNT_EMAIL=e2e@example.com
   python -m deutsch_pipeline delete --topic umwelt --database-url "$DATABASE_URL"
   ```
3. Apply with **`--yes`**:
   ```bash
   python -m deutsch_pipeline delete --topic umwelt --database-url "$DATABASE_URL" --yes
   ```
   Re-running on an already-deleted topic exits cleanly.
4. **Re-ingest** if you want the topic back (this creates fresh content; the test account's earlier progress is gone):
   ```bash
   python -m deutsch_pipeline ingest --topic umwelt --level A2 --database-url "$DATABASE_URL"
   ```

## Rollback

**Automatic (app only)**: if the deploy, the smoke check (`/healthz` and frontend load, 6 attempts at 30 s) or the production E2E fails,
the `rollback` job redeploys the previous healthy Render deploy and Vercel deployment through their APIs.
Render and Vercel are rolled back **independently**: if one fails, the other is still attempted. The job summary and the failure email
say which target rolled back and which did not.

**Partial failure** (one target was not rolled back): do it by hand.
- Render: dashboard -> service -> Deploys -> last good deploy -> *Rollback*.
- Vercel: dashboard -> project -> Deployments -> last good production deployment -> *Instant Rollback* / *Promote to Production*.

Then check `/healthz` and the frontend, and verify the API tokens in GitHub Secrets if the automatic call failed.

**Database migrations are never rolled back automatically.** If a bad migration shipped, after the app is rolled back choose one:
- **Alembic downgrade** (from `backend/`, with the Neon direct URL):
  ```bash
  DATABASE_URL="<neon direct url>" JWT_SECRET=x uv run alembic downgrade -1
  ```
- **Restore** the pre-change `pg_dump` (see [Backup and restore](#backup-and-restore)).

Make sure the schema is compatible with the rolled-back app before relying on it. Then fix forward and push to `main` to redeploy.
