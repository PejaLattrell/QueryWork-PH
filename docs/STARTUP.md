# Local FastAPI startup

Use PowerShell. This workspace keeps its Python environment at
`C:\Devs\Jobless\.venv` and its FastAPI application in `goodjob`.

## Start the existing workspace

```powershell
cd C:\Devs\Jobless\goodjob
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Leave the terminal open while using the app. Calling the environment's Python
directly means you do not need to activate it or change PowerShell's execution
policy. `--reload` restarts the app when Python source files change.

| Page | URL |
| --- | --- |
| Dashboard | http://127.0.0.1:8000/ |
| Interactive API documentation | http://127.0.0.1:8000/docs |
| Database health check | http://127.0.0.1:8000/api/v1/health |

In a second terminal, check health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

A working connection returns `status: ok` and `supabase: connected`. This verifies
database connectivity; it does not verify that the scraper is configured.

## First-time setup or missing dependencies

Install Python 3.11 or later. This example uses the Windows Python launcher's
Python 3.11 installation and preserves an existing `.venv`:

```powershell
cd C:\Devs\Jobless
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    py -3.11 -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r .\goodjob\requirements.txt
```

FastAPI loads `C:\Devs\Jobless\goodjob\.env`. Create that file only if missing:

```powershell
cd C:\Devs\Jobless
if (-not (Test-Path .\goodjob\.env)) {
    Copy-Item .\goodjob\.env.example .\goodjob\.env
}
```

Edit `goodjob\.env` with your project's values:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-publishable-key
APP_ENV=development
# Leave empty until the n8n workflow is configured and published:
N8N_WEBHOOK_URL=
```

The dashboard uses a publishable read key. Its startup does not require the
scraper's private write credential. For a new Supabase project, follow the
[database setup instructions](../goodjob/README.md#database-setup-for-another-project)
to apply the schema as well.

Run the startup command after installing dependencies and configuring `.env`.
Node.js and Docker are not needed to run FastAPI against hosted Supabase.

## Stop or restart

Press **Ctrl+C** in the server terminal to stop it. Run the same Uvicorn command
again to restart. Restart explicitly after changing `.env`; do not rely on source
reload to refresh environment settings.

## Optional: start the existing n8n service

With Docker Desktop running, use a separate terminal:

```powershell
cd C:\Devs\Jobless
docker compose -f compose.n8n.yaml up -d
```

Open http://127.0.0.1:5678/. Starting the container alone does not configure
ingestion: n8n needs its Supabase URL, private write credential, Code-node
settings, and the imported and published workflow. Follow the
[ingestion setup instructions](../goodjob/README.md#import-and-configure-n8n).
The root Compose file does not automatically load `goodjob\.env` into n8n.

Once that workflow is published, set this in `goodjob\.env` and restart FastAPI:

```dotenv
N8N_WEBHOOK_URL=http://127.0.0.1:5678/webhook/goodjob-trigger
```

Click **Run Scraper Now** and verify a completed scrape and live jobs in Supabase.
An accepted webhook request alone does not confirm that collection succeeded.
You can browse the dashboard while n8n is stopped.

The optional stack in `goodjob\docker-compose.yml` creates a separate n8n instance
on port **5679** and an app on port **8000**. This guide uses the existing root
n8n service on **5678** and FastAPI started directly with Python.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `No module named uvicorn` or another missing package | Run the dependency installation command using the same `.venv\Scripts\python.exe` used for startup. |
| `Could not import module app.main` or `No module named app` | Change directory to `C:\Devs\Jobless\goodjob` before starting Uvicorn. |
| Missing settings or a URL validation error | Check `goodjob\.env`, provide real Supabase values, and restart FastAPI. |
| Port 8000 is in use / `WinError 10048` | Check whether the dashboard is already running. Stop the existing server with Ctrl+C in its terminal, or change the startup command to `--port 8001` and open port 8001 instead. |
| Health returns 503 / `supabase: unavailable` | Check network access, Supabase project status, URL, read key, and schema setup. |
| Scraper returns `not_configured` | Configure and publish the n8n workflow, set `N8N_WEBHOOK_URL`, and restart FastAPI. |
| Scraper returns 502 | Check that n8n is running at the configured URL and the production webhook's workflow is published. |

The root `package.json` currently references missing startup and test paths. Use
the Python command in this guide to start the dashboard.
