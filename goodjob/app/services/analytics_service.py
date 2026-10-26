import asyncio

from fastapi import Request

from app.database import Database
from app.models.schemas import Filters, JobsPage, JobsQuery, Summary, Trends


class AnalyticsService:
    def __init__(self, database: Database):
        self.database = database

    async def summary(self, filters: Filters) -> Summary:
        return Summary.model_validate(await self.database.rpc('get_dashboard_summary', filters.rpc_params()))

    async def trends(self, filters: Filters) -> Trends:
        return Trends.model_validate(await self.database.rpc('get_dashboard_trends', filters.rpc_params()))

    async def jobs(self, filters: JobsQuery) -> JobsPage:
        params = filters.rpc_params() | {'p_page': filters.page, 'p_limit': filters.limit}
        return JobsPage.model_validate(await self.database.rpc('get_jobs', params))

    async def dashboard(self, filters: JobsQuery):
        summary, trends, jobs = await asyncio.gather(self.summary(filters), self.trends(filters), self.jobs(filters))
        return {'summary': summary, 'trends': trends.model_dump(mode='json'), 'jobs': jobs, 'filters': filters}


def get_analytics(request: Request) -> AnalyticsService:
    return request.app.state.analytics
