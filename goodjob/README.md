# GoodJob

A Supabase-backed technology job market dashboard with a scheduled n8n ingestion workflow. FastAPI serves the JSON API and Jinja2 HTML; HTMX refreshes filtered views and Chart.js renders hiring, skills, salary, and workplace charts.

## Current workspace

The schema migration has been applied to the connected **GoodJob** Supabase project (`bupvedycwdsajmitibpu`). The git-ignored `.env` is configured with its read-only publishable key. It contains 20 explicitly labeled **illustrative seed postings**, not verified vacancies. Seed rows never show an Apply link. There is no fabricated scrape history.

The existing root-level n8n installation and `database/schema.sql` are preserved. This implementation lives entirely in `goodjob/`, apart from additional Python cache exclusions in the root `.gitignore`.

Live ingestion requires the service-role JWT in the n8n environment and the workflow to be imported and published. No ingestion credentials were present in the connected n8n instance during implementation. `N8N_WEBHOOK_URL` is intentionally unset in the workspace `.env` until that setup is complete; the trigger endpoint returns an explicit `503 not_configured` response meanwhile.

## Run locally

Python 3.11+ and Node.js 22+ (only for workflow tests) are supported.

From this workspace on Windows:

```powershell
cd C:\Devs\Jobless\goodjob
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

On a new checkout:

```sh
cd goodjob
python -m venv .venv
# Activate .venv using your shell's activation command.
python -m pip install -r requirements.txt
cp .env.example .env
# Set SUPABASE_URL and SUPABASE_KEY in .env.
uvicorn app.main:app --reload
```

Open [the dashboard](http://127.0.0.1:8000), [health](http://127.0.0.1:8000/api/v1/health), or [interactive API documentation](http://127.0.0.1:8000/docs). Health returns 503 if the real database is unreachable. Database errors preserve the current HTMX view and show a retry message.

## Database setup for another project

Run `supabase/migrations/20261025000001_init_goodjob_schema.sql` in the Supabase SQL editor, or apply it through your connected Supabase MCP `apply_migration` tool. The migration is transactional and idempotent: tables/indexes are created if absent, views/functions are replaced, policies are recreated, and seed inserts use `ON CONFLICT (fingerprint) DO NOTHING`.

The migration creates:

- `job_postings` and `scrape_runs`, with constraints, RLS, a skills GIN index, and date/role/arrangement/source/salary indexes.
- `vw_daily_job_volume` and `vw_top_skills_demand` for the last 30 days; `vw_role_salary_benchmarks` and `vw_work_arrangement_split` for active jobs.
- `goodjob_filtered_jobs`, `get_dashboard_summary`, `get_dashboard_trends`, and `get_jobs`. All functions use invoker privileges and a fixed empty search path. The trends RPC computes the same measures as the views, with consistent filters and support for 90-day views; a fixed 30-day view cannot supply a 90-day chart.
- A public read policy for job listings and limited scrape-status columns. `error_message` is not publicly readable. Only `service_role` can insert or update. Views use `security_invoker=true`.

The summary RPC's first three optional arguments match the specification; additional optional arguments supply work arrangement, search, and minimum salary. Do not create another three-argument overload: PostgREST overload resolution would become ambiguous.

Read APIs can use a publishable key, legacy anon JWT, or service-role JWT. Prefer a publishable key for the app. Only the n8n worker needs service-role write access. Keys are never included in HTML or JavaScript responses.

## Import and configure n8n

The importable file is **`n8n/goodjob_scraper_workflow.json`**. It contains 13 fully configured nodes and imports inactive. Node types were verified against the existing n8n **2.23.2** container and the official n8n Workflow SDK validator.

1. In n8n, select **Import from File**, then choose the workflow JSON.
2. Set these variables on the n8n process/container, then restart that process:

   ```dotenv
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your-server-only-legacy-service-role-jwt
   NODE_FUNCTION_ALLOW_BUILTIN=crypto
   N8N_BLOCK_ENV_ACCESS_IN_NODE=false
   FX_USD_RATES={}
   ```

3. For this worker, allow `crypto` in the JavaScript task runner. The included Docker Compose config uses n8n's internal runner. If you use external task runners, explicitly configure the same built-in allowlist and approved environment variables on the runner. Keep this worker restricted to trusted workflow authors because it can access its environment.
4. Execute the workflow manually once. Verify the `scrape_runs` record and new `job_postings` in Supabase. A successful run records `completed`; a source or batch error records `failed` with the successful upsert count and an error summary. Detailed transport errors stay in n8n execution logs.
5. **Publish** the workflow to enable the six-hour schedule and production webhook. A saved inactive draft does not register the production webhook.
6. Set the app's `N8N_WEBHOOK_URL` to the production URL, e.g. `http://127.0.0.1:5678/webhook/goodjob-trigger` for the existing root n8n installation. Restart FastAPI to load changed settings.
7. Click **Run Scraper Now**. A `202` response means n8n accepted the request, not that ingestion finished. The dashboard polls every 60 seconds; completion updates Last scraped.

The workflow uses the requested environment-backed `apikey` and Bearer headers. Use the legacy **service_role JWT** for that exact header combination; a modern `sb_secret_` API key is not a Bearer JWT. Never put ingestion secrets into the UI, workflow JSON, source control, or client requests.

### Ingestion behavior

```text
Six-hour schedule ─┐
                  ├─ Prepare UUID → Start run → Remotive ─┐
POST webhook ─────┘                           → Arbeitnow ├─ Merge → Normalize
                                                         └─ 100-job batches → Upsert → Complete run
```

- Cron: `0 */6 * * *`, with `Asia/Manila` workflow timezone. The webhook is `POST /webhook/goodjob-trigger` and responds immediately.
- Fetches the specified Remotive software-development endpoint (limit 50) and the first Arbeitnow page. This is a bounded recent-feed collector, not an exhaustive crawler. The fetch branches converge at a Merge node; their responses are normalized together.
- Extracts 60+ canonical technology tags using bounded, case-insensitive expressions, including aliases such as Next.js → `nextjs` and Postgres → `postgresql`.
- Classifies role and seniority, strips HTML from snippets, validates HTTP(S) application URLs and dates, infers only unambiguous countries, and rejects malformed records. Naive Remotive timestamps are interpreted as UTC.
- Fingerprint: SHA-256 of lowercase, whitespace-normalized `company_name + "::" + title + "::" + source`. Repeats within one run collapse before writes; later runs merge on the unique fingerprint. Identical company/title/source records intentionally collide, even if the board gives them different external IDs.
- Salary parsing supports currency-coded annual, monthly, weekly, daily, and hourly ranges and `k` notation. Hourly uses 2,080 hours/year; daily uses 260 days/year. Raw bounds retain their original pay period; the dedicated annual USD field contains the normalized midpoint. Unknown or ambiguous amounts stay null.
- USD needs no FX setup. For non-USD salaries, provide an operator-maintained JSON map of **USD per one unit** in `FX_USD_RATES`. Without a known rate, raw currency/bounds are retained while the annual USD value stays null. Rates are not silently fabricated or refreshed.
- Upserts use batches of at most 100 jobs, merge on fingerprint, and retry transient requests up to three times. Empty feeds still finalize a zero-job run. A failed feed can coexist with successful writes from the other feed, but the overall run is marked failed. `jobs_upserted` counts successful input rows, including updates, not net-new postings. Rejected malformed rows are counted inside the normalization node.
- A process crash or unavailable Supabase can prevent final logging; monitor n8n failed executions and investigate stale `running` rows. The pipeline does not automatically close jobs missing from a bounded feed. `is_active` can be retired by a trusted maintenance process.

To change the normalizer, edit `n8n/normalize.js`, run `python n8n/build_workflow.py`, run the Node tests, and reimport the rebuilt JSON. `workflow.sdk.js` is generated validation source, not a separate production pipeline.

## API

| Route | Behavior |
|---|---|
| `GET /api/v1/health` | Real Supabase connectivity; 200 or 503 |
| `GET /api/v1/metrics/summary` | Count, last-24h posted count, mean and median salary, remote share, top companies, top skill, latest successful scrape |
| `GET /api/v1/metrics/trends` | Daily role volumes, top skills, role/seniority salary benchmarks, all four work arrangements |
| `GET /api/v1/jobs` | Exact total plus stable pagination, ordered by posted date and UUID |
| `POST /api/v1/scrape/trigger` | Async webhook request; 202 accepted, 503 not configured, 502 n8n failure, 429 cooldown |

All read endpoints share `days` (1–365, default 30), `role`, `skill` (canonical lowercase), `work_arrangement`, `search` (literal title/company substring), and `min_salary` (annual USD). Jobs adds `page` (default 1) and `limit` (1–100, default 15). Empty form values mean “all”. Invalid parameters return 422. SQL arguments are passed as JSON RPC parameters, not interpolated into query strings.

```sh
curl 'http://127.0.0.1:8000/api/v1/jobs?days=14&skill=python&work_arrangement=Remote&page=1&limit=10'
curl -X POST 'http://127.0.0.1:8000/api/v1/scrape/trigger'
```

HTMX routes are `/partials/dashboard`, `/partials/metrics`, `/partials/charts`, and `/partials/jobs`. Filter changes replace one cohesive dashboard section, keeping cards, charts, and listings aligned. Pagination preserves filters. Chart instances are destroyed before replacement. The HTML carries escaped JSON data and autoescaped job content; external application links use `noopener noreferrer`.

## Optional Docker stack

Set `SUPABASE_SERVICE_ROLE_KEY` in `.env` before starting; Compose refuses to start the worker without it.

```sh
docker compose up -d --build
```

The dashboard is [localhost:8000](http://127.0.0.1:8000); the optional stack's n8n is [localhost:5679](http://127.0.0.1:5679), avoiding the existing root n8n on port 5678. Inside Compose, FastAPI calls `http://n8n:5678/webhook/goodjob-trigger`. Import/publish the workflow in this new instance as described above. Stop a manually running Uvicorn on port 8000 before starting this stack.

The dedicated `goodjob-platform_n8n_data` named volume persists workflows and credentials. `docker compose stop` preserves it. Do not use `down -v` unless you intend to delete its data. The Docker app runs as a non-root user. A Docker image build was not run as part of verification; the Compose configuration was validated without starting another stack.

## Deployment and operations

For a network-accessible deployment, set `APP_ENV=production` and a random `APP_TRIGGER_TOKEN` of at least 24 characters. Startup enforces that requirement. Provide the token in the dashboard's password field or `X-Scrape-Token` header; it is not embedded into the page. Cross-origin browser scrape requests are rejected. Protect the n8n production webhook at your reverse proxy if it is reachable beyond localhost/the private container network.

The included default ports bind to loopback. Place the app behind your organization's authentication/TLS proxy for shared deployments. Trigger cooldown defaults to 300 seconds and is **per app process**; use one Uvicorn worker or enforce a shared rate limit upstream when scaling. A single worker handles requests asynchronously and shares pooled HTTP connections.

Tailwind, HTMX, and Chart.js are pinned CDN imports as requested, so the browser needs access to those hosts. The UI shows an explicit notice if Chart.js cannot load. For deployments with restrictive CSP/offline requirements, vendor those libraries and compile Tailwind as a separate packaging step.

The salary KPI is the median of annualized posting midpoints. Benchmark min/max describe those posting midpoints, not the widest advertised salary endpoints. Salary figures use the disclosed-pay subset; sample size is shown. Velocity uses `posted_at`, not the number of newly scraped records. Date buckets use UTC. Summary mean is also available through the API.

The 20 seed records remain until explicitly retired; all market measures include matching seed records and display an on-page sample notice. To switch to live data only after your first successful ingestion, a database administrator can run:

```sql
update public.job_postings set is_active=false where source='seed';
```

## Verification

From `goodjob/`:

```sh
python -m pytest -q
node --test tests/*.test.cjs
# Requires configured .env, network access, and a running local app:
python -m tests.live_smoke
# Optional public-feed contract check; normalizes without database writes:
node tests/live_feeds.cjs
```

The suite covers shared filtering, validation, HTML escaping, all partials, health/database outages, honest disconnected-scraper behavior, trigger authorization/cooldown/upstream failures, salary conversions, skill aliases, fingerprints, feed deduplication/failure handling, and workflow graph integrity. Live smoke checks verify all four database views, RPC count consistency, exact filtered results, public write denial using an empty payload, pagination, and the rendered dashboard.

Verified during implementation: 13 API tests and 11 JavaScript tests passed; live Supabase smoke checks passed; the official n8n SDK validator accepted all 13 workflow nodes without warnings; Supabase security advisors returned no findings. The JavaScript suite includes chart initialization after DOM readiness, chart replacement after HTMX settles, batch boundaries, and accurate partial-failure counts. Performance advisors reported informational unused indexes on the fresh 20-row dataset. Those indexes are intentionally retained for production workloads.

The public-feed contract check fetched 310 records and normalized them into 299 unique postings (10 Remotive, 289 Arbeitnow) with no rejected records or source errors at verification time. This was a read-only check; those records were not inserted into the database. Feed sizes and contents change over time.

## References

- [Supabase row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [n8n HTTP Request node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/)
- [n8n Code node built-in modules](https://docs.n8n.io/hosting/configuration/configuration-examples/modules-in-code-node/)
- [Remotive public API](https://github.com/remotive-com/remote-jobs-api)
- [Arbeitnow job board API](https://www.arbeitnow.com/api/job-board-api)
