from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR
from app.models.schemas import Filters, JobsQuery, ROLES
from app.services.analytics_service import AnalyticsService, get_analytics

router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / 'templates')


def ago(value):
    if value is None:
        return 'Never'
    seconds = max(0, (datetime.now(timezone.utc) - value).total_seconds())
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{int(seconds // 60)}m ago'
    if seconds < 86400:
        return f'{int(seconds // 3600)}h ago'
    return f'{int(seconds // 86400)}d ago'


templates.env.filters['ago'] = ago
templates.env.filters['money'] = lambda value: f'${value / 1000:,.0f}k' if value is not None else 'Not disclosed'
templates.env.globals['page_url'] = lambda filters, page: '/partials/jobs?' + urlencode(filters.model_dump(exclude_none=True) | {'page': page})
Service = Annotated[AnalyticsService, Depends(get_analytics)]


@router.get('/')
async def dashboard(request: Request, filters: Annotated[JobsQuery, Query()], service: Service):
    context = await service.dashboard(filters)
    context.update(roles=ROLES, token_required=bool(request.app.state.settings.app_trigger_token))
    return templates.TemplateResponse(request=request, name='dashboard.html', context=context)


@router.get('/partials/dashboard')
async def dashboard_partial(request: Request, filters: Annotated[JobsQuery, Query()], service: Service):
    return templates.TemplateResponse(request=request, name='partials/dashboard_content.html', context=await service.dashboard(filters))


@router.get('/partials/metrics')
async def metrics_partial(request: Request, filters: Annotated[Filters, Query()], service: Service):
    return templates.TemplateResponse(request=request, name='partials/kpi_cards.html', context={'summary': await service.summary(filters)})


@router.get('/partials/charts')
async def charts_partial(request: Request, filters: Annotated[Filters, Query()], service: Service):
    return templates.TemplateResponse(request=request, name='partials/charts_section.html', context={'trends': (await service.trends(filters)).model_dump(mode='json'), 'filters': filters})


@router.get('/partials/jobs')
async def jobs_partial(request: Request, filters: Annotated[JobsQuery, Query()], service: Service):
    return templates.TemplateResponse(request=request, name='partials/jobs_table.html', context={'jobs': await service.jobs(filters), 'filters': filters})
