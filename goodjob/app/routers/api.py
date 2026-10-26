import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.models.schemas import Filters, JobsPage, JobsQuery, Summary, Trends, TriggerResponse
from app.services.analytics_service import AnalyticsService, get_analytics

router = APIRouter(prefix='/api/v1')
Analytics = Annotated[AnalyticsService, Depends(get_analytics)]


@router.get('/health')
async def health(request: Request):
    connected = await request.app.state.database.healthy()
    return JSONResponse({'status': 'ok' if connected else 'degraded', 'supabase': 'connected' if connected else 'unavailable'}, status_code=200 if connected else 503)


@router.get('/metrics/summary', response_model=Summary)
async def summary(filters: Annotated[Filters, Query()], service: Analytics):
    return await service.summary(filters)


@router.get('/metrics/trends', response_model=Trends)
async def trends(filters: Annotated[Filters, Query()], service: Analytics):
    return await service.trends(filters)


@router.get('/jobs', response_model=JobsPage)
async def jobs(filters: Annotated[JobsQuery, Query()], service: Analytics):
    return await service.jobs(filters)


@router.post('/scrape/trigger', response_model=TriggerResponse)
async def trigger(request: Request):
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, 'Cross-origin scrape requests are not allowed')
    expected = request.app.state.settings.app_trigger_token
    if expected and not secrets.compare_digest(request.headers.get('x-scrape-token', ''), expected.get_secret_value()):
        raise HTTPException(401, 'A valid scraper access token is required')
    result = await request.app.state.n8n.trigger()
    code = 202 if result.status == 'accepted' else 503
    if request.headers.get('hx-request') == 'true':
        return HTMLResponse(f'<span role="status">{result.message}</span>', status_code=code)
    return JSONResponse(result.model_dump(mode='json'), status_code=code)
