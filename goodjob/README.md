# GoodJob application

A local technology job market dashboard with a pure Python ingestion framework. FastAPI serves JSON and Jinja2 HTML, HTMX refreshes filtered views, and Chart.js draws the charts. The framework has CLI and application entry points, but no sources have been selected or implemented: the empty source registry disables collection and replay.

## Implementation and scope

The current application lives in `goodjob/`. Its schema is `supabase/migrations/20261025000001_init_goodjob_schema.sql`. The root `database/schema.sql` belongs to an earlier prototype.

The migration includes 20 synthetic illustrative seed postings. They are explicitly labeled, never show an Apply link, and contribute to matching charts until retired. These demonstration rows are not a selected job site or verified vacancies. Source selection and Philippine market coverage remain undecided.

Python implements the framework mechanisms for raw preservation, retries, generic normalization, replay, batched Supabase writes, and run reporting. Isolated fixtures exercise those mechanisms without selecting a live provider. An authorized source and its adapter must be chosen and implemented before ingestion can run. Databricks upload, Bronze/Silver/Gold processing, and atomic Gold publication remain planned in the [architecture](../docs/architecture.MD).

## Run locally

Use Python 3.11 or later. Node.js is optional for chart tests, not required for ingestion.

```powershell
cd C:\Devs\Jobless
.\.venv\Scripts\python.exe -m pip install -r .\goodjob\requirements.txt
cd goodjob
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

On first setup, create the virtual environment and copy `.env.example` to `.env` only if the latter is missing. See [STARTUP.md](../docs/STARTUP.md) for exact commands.

Open the [dashboard](http://127.0.0.1:8000/), [health endpoint](http://127.0.0.1:8000/api/v1/health), or [API documentation](http://127.0.0.1:8000/docs). Health verifies database read connectivity, not ingestion completion.

## Configuration

FastAPI and the CLI load `goodjob/.env`. Never commit real credentials.

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-publishable-or-anon-read-key
# Optional for browsing; retained for future ingestion. Does not enable a source.
SUPABASE_SERVICE_ROLE_KEY=
FX_USD_RATES={}
INGESTION_LANDING_DIR=.local/ingestion
APP_ENV=development
APP_TRIGGER_TOKEN=
SCRAPE_COOLDOWN_SECONDS=300
```

Relative landing paths resolve against `goodjob/`; the default is `goodjob/.local/ingestion`. The currently disabled collector does not create raw archives. Preserve any existing archive for future recovery. A read key is enough for the dashboard. The optional write credential is server-only; it cannot activate collection or replay while the registry is empty.

`FX_USD_RATES` is a JSON map of positive, finite **USD per one unit of currency**. Unknown rates leave annual USD null while retaining parsed original bounds and currency. No rates are invented or refreshed automatically.

For network-accessible use, set `APP_ENV=production` and a random `APP_TRIGGER_TOKEN` of at least 24 characters. Users provide it in the dashboard password field or `X-Scrape-Token` header. Cross-origin browser trigger requests are rejected. The default listener remains loopback.

## Python ingestion

Inspect the CLI without enabling any source:

```powershell
cd C:\Devs\Jobless\goodjob
..\.venv\Scripts\python.exe -m ingestion --help
..\.venv\Scripts\python.exe -m ingestion
```

`--help` displays usage. The default command currently prints `Ingestion is not configured: no sources have been selected. Choose and implement an authorized source before collecting.` and exits 2 before reading settings, making ingestion HTTP requests, writing to the database, or creating a landing batch. A write key does not change that result.

The CLI retains a replay interface for the framework, but replay is also disabled before HTTP while the source registry is empty:

```powershell
..\.venv\Scripts\python.exe -m ingestion --replay .local/ingestion/<run-uuid>
```

The replay command currently exits 2 with the same no-source message, even if the path exists. `--landing-dir PATH` remains a future archive destination override. The framework's configured-fixture paths cover exit 0 for completion, 1 for a failed collection/publication, 2 for invalid configuration/archive input, and 130 for interruption; these do not establish live source availability.

The dashboard collection action and `POST /api/v1/scrape/trigger` currently report 503 `not_configured` because no sources have been selected, even when a write key is set. No runner or background collection is started. The dashboard polls `GET /api/v1/scrape/status` every five seconds; analytics data refreshes every 60 seconds and can display synthetic seed or existing records.

If a source adapter is explicitly chosen and implemented later, the framework can accept a background task with 202 and enforce running/cooldown responses with 429. HTTP task state belongs to one app process. Future CLI and dashboard collection must not run concurrently without shared control; use one Uvicorn worker initially. No automatic schedule is installed.

There is currently no live collection task to cancel. The framework's shutdown behavior cancels an active configured task; an abrupt stop could leave an unfinished run after sources are introduced. Preserve raw archives for later recovery. The computer must stay awake for the local dashboard and any future local collection/schedule.

### Framework mechanisms tested with isolated fixtures

- No live fetch is configured. Fixture adapters exercise explicit timeouts and at most three attempts for transient errors. Retry handling respects `Retry-After` up to 60 seconds; invalid or longer waits stop collection instead of retrying early.
- Archive every received HTTP response, including retry errors, before parsing or normalization.
- Each run directory contains `manifest.json`, `SOURCE-attempt-N.body` bytes, and `SOURCE-attempt-N.json` metadata: source, sanitized request URL, retrieval time, HTTP status/content type, raw filename, SHA-256, and byte count.
- Replay verifies saved content and reuses the run ID without making source requests.
- Source-neutral helpers validate canonical records, strip markup, classify roles/seniority, and extract canonical skill tags. They are not provider-specific response adapters. A future adapter must supply fields such as `external_id`, `title`, `company_name`, `job_url`, and timezone-aware ISO `posted_at`.
- Fingerprints hash source plus stable external job ID. Distinct vacancies sharing employer/title remain distinct; repeated observations upsert the same identity.
- Salary parsing supports annual/monthly/weekly/daily/hourly ranges and `k` notation. Hourly annualization uses 2,080 hours and daily uses 260 days. Annual USD is the normalized posting midpoint.
- Publish batches of at most 100 rows. `jobs_upserted` counts successful input rows, including updates, not net-new vacancies. A valid empty feed can succeed.
- A fetch, run-history, or batch-publication failure keeps the run failed. Direct prototype publication is not atomic: earlier successful batches can already be visible when a later batch fails.
- A missing listing in a bounded feed does not prove closure. No automatic closing policy is applied.

The source-ID identity helper differs from the earlier title-based prototype. If ingestion is enabled later, review existing live rows before using that identity scheme on a populated project; reconciling older records requires an explicit data operation. The currently disabled framework performs no database cleanup.

## Database setup

Apply `supabase/migrations/20261025000001_init_goodjob_schema.sql` using the SQL editor or project migration tooling. It creates `job_postings`, `scrape_runs`, indexes, four analytical views, and the functions `goodjob_filtered_jobs`, `get_dashboard_summary`, `get_dashboard_trends`, and `get_jobs`.

Public read policies expose listings and limited run-status columns; detailed errors are not publicly readable. Only the privileged ingestion role writes. Views use `security_invoker=true`; functions use invoker privileges and an empty search path.

The shared SQL filter helper keeps cards/charts/listings consistent. Python models validate request/response shapes; they do not create tables. Keep SQL argument signatures compatible with app calls and avoid overlapping function overloads that confuse PostgREST.

Salary KPIs and benchmark extrema describe annualized posting midpoints on the disclosed-pay subset, with sample size. Posting volume uses source `posted_at` and UTC date buckets. Regional eligibility and monthly PHP benchmarks remain future work.

## API

| Route | Behavior |
| --- | --- |
| `GET /api/v1/health` | Read connectivity, 200 or 503 |
| `GET /api/v1/metrics/summary` | Counts, salary statistics, remote share, companies, top skill, last completed scrape |
| `GET /api/v1/metrics/trends` | Daily role volumes, skills, salary benchmarks, arrangement split |
| `GET /api/v1/jobs` | Exact total and stable pagination by posted date/UUID |
| `POST /api/v1/scrape/trigger` | Currently 503 `not_configured`: source registry empty, no ingestion started |
| `GET /api/v1/scrape/status` | App-owned task state, run ID, counts, and safe message |

Read filters are `days` (1–365), `role`, `skill`, `work_arrangement`, `search`, and `min_salary` (annual USD). Jobs adds `page` and `limit` (1–100). Empty values mean all matches; invalid parameters return 422. Private transport errors are excluded from public status responses.

HTMX routes are `/partials/dashboard`, `/partials/metrics`, `/partials/charts`, and `/partials/jobs`. Filter changes replace the whole filtered section; pagination replaces the table. Chart instances are cleaned up before replacement and redrawn after settling. HTML is autoescaped and external application links use `noopener noreferrer`.

## Code structure and modularity

| Location | Responsibility |
| --- | --- |
| `app/main.py` | Constructs shared clients/services; manages startup/shutdown and global errors/security. |
| `app/config.py` | Loads and validates configuration outside routes. |
| `app/models/schemas.py` | Shared filters and response contracts for JSON and HTML. |
| `app/routers/api.py` | HTTP API, trigger authorization, and task status. |
| `app/routers/ui.py` | Full-page and partial HTML rendering through the shared analytics service. |
| `app/services/analytics_service.py` | Coordinates SQL-function calls and validates results. |
| `app/database.py` | Supabase read HTTP access, authentication, timeouts, and error translation. |
| `app/services/ingestion_service.py` | Local background task, running state, cooldown, and safe status messages. |
| `ingestion/normalize.py` | Source-neutral canonical-record validation and salary, skill, role, date, and identity helpers. |
| `ingestion/runner.py` | Empty source registry and guarded collection/replay; preservation, retries, and publication mechanisms tested with fixtures. |
| `ingestion/__main__.py` | CLI help and no-source configuration result before ingestion work. |
| `app/templates/` and `app/static/js/` | HTML composition and browser chart/status behavior. |
| `supabase/migrations/` | Database structure, permissions, filters, and analytical calculations. |
| `tests/` | Offline checks and separate explicit live checks. |

A filter goes from the shared schema through either router, the analytics service, the database client, and a SQL function. Its result becomes HTML or JSON. Adding a filter requires its schema, SQL rule, and form field; both interfaces reuse the implementation.

The read client and ingestion runner have separate credentials/lifecycles. `create_app` accepts supplied dependencies so tests can exercise behavior without real services.

## Optional local container

From `goodjob/`:

```powershell
docker compose up -d --build
```

Compose runs one application with the source-disabled Python framework included, bound to `127.0.0.1:8000`. The named `ingestion_data` volume reserves `/srv/goodjob/.local`; the configured future landing directory is `/srv/goodjob/.local/ingestion`. A write key is optional for browsing and does not enable collection. The image runs as a non-root user.

Stopping containers preserves any archive volume content; deleting volumes deletes it. Restarting does not preserve in-memory task state/cooldown. Docker is optional; direct Python startup runs the same dashboard and guarded framework. Local execution requires the PC awake.

## Checks and operations

From `goodjob/`:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
# Optional chart lifecycle checks:
node --test tests/charts.test.cjs
# Explicit live database/application check; requires configured .env and running FastAPI:
..\.venv\Scripts\python.exe -m tests.live_smoke
```

Offline checks cover filters, escaping, ingestion configuration/auth/status/cooldown, preservation, normalization, retries, batches, and failures. Explicit live checks require separate operator intent and source permission. Report verification from the actual run rather than treating a historical test count as a guarantee.

Browser libraries use pinned CDN imports, so their hosts must be reachable. The dashboard reports chart-loading failure. Before unattended collection, measure archive growth, define retention/backups, check Supabase Free usage, and investigate unfinished runs. See the [architecture](../docs/architecture.MD) for limits and future publication.
