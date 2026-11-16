# Local Python startup and ingestion

Use PowerShell. This workspace keeps its Python environment at `C:\Devs\Jobless\.venv` and the FastAPI application plus ingestion package in `goodjob/`.

## First-time setup

Use Python 3.11 or later. Preserve an existing virtual environment and configuration:

```powershell
cd C:\Devs\Jobless
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    py -3.11 -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r .\goodjob\requirements.txt
if (-not (Test-Path .\goodjob\.env)) {
    Copy-Item .\goodjob\.env.example .\goodjob\.env
}
```

Edit `goodjob/.env` with the project's URL and read key:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-publishable-or-anon-read-key
APP_ENV=development
SUPABASE_SERVICE_ROLE_KEY=
FX_USD_RATES={}
INGESTION_LANDING_DIR=.local/ingestion
SCRAPE_COOLDOWN_SECONDS=300
```

The dashboard needs only the URL and read key. No ingestion sources are selected, and the source registry is empty. Leave the optional write credential blank; setting it cannot enable ingestion without an explicitly chosen and implemented adapter. For a new Supabase project, follow the [database setup](../goodjob/README.md#database-setup) as well.

## Start the dashboard

```powershell
cd C:\Devs\Jobless\goodjob
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Leave this terminal open. Calling the environment's Python directly avoids activation or changing PowerShell's execution policy.

| Page | URL |
| --- | --- |
| Dashboard | http://127.0.0.1:8000/ |
| API documentation | http://127.0.0.1:8000/docs |
| Database read health | http://127.0.0.1:8000/api/v1/health |
| App-owned ingestion status | http://127.0.0.1:8000/api/v1/scrape/status |

A successful health request proves database read access, not live source availability. Browse existing records or explicitly labeled synthetic seed rows. Collection and replay remain disabled while the registry is empty.

## Inspect the Python CLI while sources are undecided

Use the CLI help or inspect its current configuration result:

```powershell
cd C:\Devs\Jobless\goodjob
..\.venv\Scripts\python.exe -m ingestion --help
..\.venv\Scripts\python.exe -m ingestion
```

`--help` displays usage. The default command prints `Ingestion is not configured: no sources have been selected. Choose and implement an authorized source before collecting.` and exits 2 before reading settings, making ingestion HTTP requests, writing to the database, or creating a landing batch. This is expected with or without a write credential.

Replay is also disabled before ingestion HTTP while no source adapter exists. The framework's archive/checksum/retry/replay mechanisms are covered by isolated fixture tests. If sources are explicitly selected and implemented later, the configured local archive path is `goodjob/.local/ingestion`; relative `INGESTION_LANDING_DIR` values resolve against `goodjob/`.

The dashboard collection action reports 503 `not_configured` with `Collection is not configured: ingestion sources have not been selected.` No writer runner or background task starts. Status polls on initial page load and every five seconds, while dashboard read data refreshes every 60 seconds.

No automatic schedule is enabled. Future collection requires a separately chosen/tested adapter, source permission, and an explicit concurrency rule. CLI and app processes do not share a lock; use one Uvicorn worker initially. The dashboard and any future local collection/schedule require the PC awake and relevant process running.

## Stop or restart

Press **Ctrl+C** in the server terminal. Run the startup command again to restart. Restart explicitly after changing `.env`.

There is currently no live collection task to cancel. The framework's shutdown handling cancels an active configured task, as tested with fixtures. Preserve any existing archived originals; replay remains disabled until sources are explicitly introduced.

## Optional container packaging

Python startup is sufficient; Docker is optional. With a working local Docker engine:

```powershell
cd C:\Devs\Jobless\goodjob
docker compose up -d --build
```

Compose runs one app on `127.0.0.1:8000` with the source-disabled Python framework included. Its `ingestion_data` volume reserves `/srv/goodjob/.local`, with `/srv/goodjob/.local/ingestion` configured for future raw archives. No collection is activated by container startup or credentials. Container restart loses in-memory task state/cooldown; preserve any existing volume content. The container is local and requires the PC awake.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing Python module | Install `goodjob/requirements.txt` using the same virtual environment used for startup. |
| Cannot import `app` or `ingestion` | Change directory to `C:\Devs\Jobless\goodjob` before invoking the module. |
| Health returns 503 | Check Supabase project status, URL, read key, network connectivity, and migration setup. |
| Collection/replay returns `not_configured` | Expected: no source has been selected or implemented. A write key does not change the empty registry. |
| Need to enable live collection later | Make source selection an explicit decision, validate its terms/limits, implement its adapter, and prove it with fixtures before a live run. |
| Port 8000 is occupied | Stop the existing server or explicitly select another port. |
| Saved originals disappear after container recreation | Check that the existing archive volume is mounted; do not delete its contents during routine restart. |

Run offline checks from `goodjob/` with `..\.venv\Scripts\python.exe -m pytest -q`. Node.js is needed only for the optional chart checks: `node --test tests/charts.test.cjs`. Neither Node.js nor Docker is required for Python ingestion.
