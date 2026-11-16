import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.ingestion_service import IngestionService


SUMMARY = dict(total_jobs=1, jobs_added_last_24h=1, avg_annual_salary_usd=120000,
                median_annual_salary_usd=120000, salary_sample_size=1, seed_job_count=1,
                remote_percentage=100, top_hiring_companies=[dict(company_name='<script>bad</script>', job_count=1)],
                top_skill=dict(skill='python', mention_count=1), last_scrape_at=None)
TRENDS = dict(daily_volume=[], top_skills=[], salary_benchmarks=[], work_arrangements=[])
NOW = datetime.now(timezone.utc).isoformat()
JOB = dict(id='00000000-0000-0000-0000-000000000001', external_id='1', fingerprint='a'*64,
            title='<script>alert(1)</script>', company_name='Company', normalized_role='Backend Engineer',
            work_arrangement='Remote', skills=['python'], job_url='https://example.com', source='seed',
            posted_at=NOW, scraped_at=NOW, is_active=True)


class FakeRunner:
    def __init__(self, *, failed=False, crash=False):
        self.calls = 0
        self.closed = False
        self.crash = crash
        self.result = SimpleNamespace(status='failed' if failed else 'completed', run_id='test-run',
                                      jobs_found=2, jobs_upserted=1 if failed else 2, rejected=0,
                                      errors=['private-upstream-detail'] if failed else [])

    async def run(self):
        self.calls += 1
        if self.crash:
            raise RuntimeError('private-upstream-detail')
        return self.result

    async def close(self):
        self.closed = True


class BlockingRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()
        self.cancelled = False

    async def run(self):
        self.calls += 1
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.result


async def wait_for_collection(service):
    await asyncio.wait_for(asyncio.shield(service._task), timeout=2)


def setup_client(*, unavailable=False, token=None, runner=None):
    calls = []
    settings = Settings(_env_file=None, supabase_url='https://test.supabase.co', supabase_key='sb_publishable_test',
                        app_trigger_token=token, app_env='test')

    def database_handler(request):
        if unavailable:
            return httpx.Response(503, json={'message': 'unavailable'})
        if request.method == 'GET':
            return httpx.Response(200, json=[])
        params = json.loads(request.content)
        calls.append((request.url.path, params))
        if request.url.path.endswith('get_dashboard_summary'):
            body = SUMMARY
        elif request.url.path.endswith('get_dashboard_trends'):
            body = TRENDS
        else:
            body = dict(items=[JOB], total=2, page=params['p_page'], limit=params['p_limit'])
        return httpx.Response(200, json=body)

    db = Database(settings, transport=httpx.MockTransport(database_handler))
    ingestion = IngestionService(settings, runner=runner)
    return TestClient(create_app(settings, db, ingestion)), calls


def test_all_filters_reach_every_analytics_rpc():
    client, calls = setup_client()
    query = '?days=7&role=Backend+Engineer&skill=PYTHON&work_arrangement=Remote&search=hello%25%2Cworld&min_salary=50000'
    with client:
        for endpoint in ['/api/v1/metrics/summary', '/api/v1/metrics/trends', '/api/v1/jobs']:
            assert client.get(endpoint + query).status_code == 200
    assert len(calls) == 3
    for _, params in calls:
        assert params['p_skill'] == 'python'
        assert params['p_search'] == 'hello%,world'
        assert params['p_work_arrangement'] == 'Remote'
        assert params['p_min_salary'] == 50000
        assert params['p_days'] == 7


def test_dashboard_and_partials_escape_posting_content():
    client, _ = setup_client()
    with client:
        for path in ['/', '/partials/dashboard', '/partials/jobs', '/partials/charts', '/partials/metrics']:
            response = client.get(path + '?role=&skill=&work_arrangement=&search=')
            assert response.status_code == 200, response.text
            assert '<script>alert(1)</script>' not in response.text
        html = client.get('/').text
        assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
        assert 'Sample' in html
        assert 'Apply ↗' not in html
        assert html.count('<canvas') == 4


@pytest.mark.parametrize('query', ['days=0','days=366','page=0','limit=101','work_arrangement=Anywhere','min_salary=-1'])
def test_invalid_query_is_rejected(query):
    client, _ = setup_client()
    with client:
        assert client.get('/api/v1/jobs?' + query).status_code == 422


def test_missing_write_credential_is_honest_and_htmx_readable():
    client, _ = setup_client()
    with client:
        result = client.post('/api/v1/scrape/trigger')
        assert result.status_code == 503
        assert result.json()['status'] == 'not_configured'
        result = client.post('/api/v1/scrape/trigger', headers={'HX-Request': 'true'})
        assert result.status_code == 503 and 'not configured' in result.text
        assert client.get('/api/v1/scrape/status').json()['status'] == 'not_configured'
        assert client.get('/api/v1/jobs').status_code == 200


def test_trigger_auth_cooldown_and_cross_origin():
    runner = FakeRunner()
    client, _ = setup_client(runner=runner, token='secret')
    with client:
        assert client.post('/api/v1/scrape/trigger').status_code == 401
        headers = {'X-Scrape-Token': 'secret'}
        assert client.post('/api/v1/scrape/trigger', headers=headers | {'Origin': 'https://other.example'}).status_code == 403
        assert client.post('/api/v1/scrape/trigger', headers=headers).status_code == 202
        limited = client.post('/api/v1/scrape/trigger', headers=headers)
        assert limited.status_code == 429 and int(limited.headers['retry-after']) > 0
    assert runner.calls == 1 and runner.closed


def test_background_collection_does_not_block_reads_and_rejects_overlap():
    runner = BlockingRunner()
    client, _ = setup_client(runner=runner)
    with client:
        assert client.post('/api/v1/scrape/trigger').status_code == 202
        assert client.get('/api/v1/scrape/status').json()['status'] == 'running'
        assert client.get('/api/v1/jobs').status_code == 200
        # Even after cooldown has elapsed, the running collection blocks overlap.
        client.portal.call(setattr, client.app.state.ingestion, '_last_trigger', float('-inf'))
        assert client.post('/api/v1/scrape/trigger').status_code == 429
        client.portal.call(runner.release.set)
        client.portal.call(wait_for_collection, client.app.state.ingestion)
        result = client.get('/api/v1/scrape/status').json()
        assert result['status'] == 'completed' and result['jobs_upserted'] == 2
        assert runner.calls == 1
    assert runner.closed


@pytest.mark.parametrize('crash', [False, True])
def test_background_failure_is_visible_without_exposing_error_details(crash):
    runner = FakeRunner(failed=True, crash=crash)
    client, _ = setup_client(runner=runner)
    with client:
        assert client.post('/api/v1/scrape/trigger').status_code == 202
        client.portal.call(wait_for_collection, client.app.state.ingestion)
        result = client.get('/api/v1/scrape/status')
        assert result.json()['status'] == 'failed'
        assert result.json()['jobs_upserted'] == (0 if crash else 1)
        assert 'private-upstream-detail' not in result.text
        html = client.get('/api/v1/scrape/status', headers={'HX-Request': 'true'})
        assert 'Collection failed' in html.text
    assert runner.closed


def test_shutdown_cancels_collection_and_closes_runner():
    runner = BlockingRunner()
    client, _ = setup_client(runner=runner)
    with client:
        assert client.post('/api/v1/scrape/trigger').status_code == 202
        assert client.get('/api/v1/scrape/status').json()['status'] == 'running'
    assert runner.cancelled and runner.closed


def test_concurrent_triggers_start_only_one_collection():
    async def scenario():
        settings = Settings(_env_file=None, supabase_url='https://test.supabase.co',
                            supabase_key='sb_publishable_test', app_env='test')
        runner = BlockingRunner()
        service = IngestionService(settings, runner=runner)
        try:
            responses = await asyncio.gather(service.trigger(), service.trigger(), return_exceptions=True)
            assert sum(getattr(response, 'status', None) == 'accepted' for response in responses) == 1
            assert sum(isinstance(response, HTTPException) and response.status_code == 429 for response in responses) == 1
            await asyncio.sleep(0)
            assert runner.calls == 1
        finally:
            await service.close()
    asyncio.run(scenario())


def test_database_outage_is_visible():
    client, _ = setup_client(unavailable=True)
    with client:
        assert client.get('/api/v1/health').status_code == 503
        assert client.get('/api/v1/metrics/summary').status_code == 503
        assert client.get('/').status_code == 503


def test_production_requires_access_token():
    with pytest.raises(ValueError, match='APP_TRIGGER_TOKEN'):
        Settings(_env_file=None, supabase_url='https://test.supabase.co', supabase_key='x', app_env='production')
