"""Read-only smoke checks against the configured Supabase project and local server."""
import asyncio

import httpx

from app.config import get_settings
from app.database import Database


async def main():
    database = Database(get_settings())
    try:
        assert await database.healthy(), 'Supabase connection failed'
        params = dict(p_days=30, p_role=None, p_skill=None, p_work_arrangement=None, p_search=None, p_min_salary=None)
        summary = await database.rpc('get_dashboard_summary', params)
        jobs = await database.rpc('get_jobs', params | dict(p_page=1, p_limit=100))
        trends = await database.rpc('get_dashboard_trends', params)
        assert summary['total_jobs'] == jobs['total']
        assert sum(row['job_count'] for row in trends['daily_volume']) == summary['total_jobs']
        assert sum(row['job_count'] for row in trends['work_arrangements']) == summary['total_jobs']
        selected = params | dict(p_days=7, p_skill='python', p_work_arrangement='Remote')
        filtered = await database.rpc('get_jobs', selected | dict(p_page=1, p_limit=100))
        filtered_summary = await database.rpc('get_dashboard_summary', selected)
        assert filtered['total'] == filtered_summary['total_jobs']
        assert all('python' in row['skills'] and row['work_arrangement'] == 'Remote' for row in filtered['items'])
        empty = await database.rpc('get_dashboard_summary', params | dict(p_search='impossible-query-8c173e'))
        assert empty['total_jobs'] == 0 and empty['median_annual_salary_usd'] is None
        for view in ['vw_daily_job_volume','vw_top_skills_demand','vw_role_salary_benchmarks','vw_work_arrangement_split']:
            result = await database.client.get(view, params={'limit': 1})
            assert result.status_code == 200, (view, result.text)
        # An empty write cannot add records, even if permissions regress.
        result = await database.client.post('job_postings', json=[])
        assert result.status_code in (401,403), 'Public key unexpectedly has write access'
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=25) as client:
            for endpoint in ['/api/v1/health','/api/v1/metrics/summary','/api/v1/metrics/trends','/api/v1/jobs?page=2','/partials/dashboard?skill=python','/']:
                response = await client.get(endpoint)
                assert response.status_code == 200, (endpoint, response.text[:300])
            assert (await client.get('/api/v1/jobs?page=0')).status_code == 422
        print(f'Live smoke passed: {summary["total_jobs"]} jobs, {filtered["total"]} filtered jobs; all views, RPCs, public write denial, HTML and API routes verified.')
    finally:
        await database.close()


if __name__ == '__main__':
    asyncio.run(main())
