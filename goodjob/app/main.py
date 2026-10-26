import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, Settings, get_settings
from app.database import Database, DatabaseUnavailable
from app.routers import api, ui
from app.services.analytics_service import AnalyticsService
from app.services.n8n_service import N8NService


def create_app(settings: Settings | None = None, database: Database | None = None, n8n: N8NService | None = None):
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configuration = settings or get_settings()
        application.state.settings = configuration
        application.state.database = database or Database(configuration)
        application.state.analytics = AnalyticsService(application.state.database)
        application.state.n8n = n8n or N8NService(configuration)
        logging.basicConfig(level=logging.INFO)
        yield
        await application.state.database.close()
        await application.state.n8n.close()

    application = FastAPI(title='GoodJob', version='1.0.0', lifespan=lifespan)
    application.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
    application.include_router(api.router)
    application.include_router(ui.router)

    @application.exception_handler(DatabaseUnavailable)
    async def database_error(request: Request, exc: DatabaseUnavailable):
        if request.url.path.startswith('/api/'):
            return JSONResponse({'detail': str(exc)}, status_code=503)
        return ui.templates.TemplateResponse(request=request, name='error.html', context={'message': str(exc), 'partial': request.headers.get('hx-request') == 'true'}, status_code=503)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if request.headers.get('hx-request') == 'true':
            from html import escape
            return HTMLResponse(f'<span role="alert">{escape(str(exc.detail))}</span>', status_code=exc.status_code, headers=exc.headers)
        return await http_exception_handler(request, exc)

    @application.middleware('http')
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith(('/api/', '/partials/')) or request.url.path == '/' else 'public, max-age=3600'
        return response

    return application


app = create_app()
