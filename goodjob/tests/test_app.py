import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.n8n_service import N8NService


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


def setup_client(*, unavailable=False, webhook=None, token=None, upstream_status=200):
    calls = []
    settings = Settings(_env_file=None, supabase_url='https://test.supabase.co', supabase_key='sb_publishable_test',
                        n8n_webhook_url=webhook, app_trigger_token=token, app_env='test')

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
    n8n = N8NService(settings, transport=httpx.MockTransport(lambda request: httpx.Response(upstream_status, json={'accepted': True})))
    return TestClient(create_app(settings, db, n8n)), calls


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


def test_disconnected_n8n_is_honest_and_htmx_readable():
    client, _ = setup_client()
    with client:
        result = client.post('/api/v1/scrape/trigger')
        assert result.status_code == 503
        assert result.json()['status'] == 'not_configured'
        result = client.post('/api/v1/scrape/trigger', headers={'HX-Request': 'true'})
        assert result.status_code == 503 and 'not connected' in result.text


def test_trigger_auth_cooldown_and_cross_origin():
    client, _ = setup_client(webhook='https://n8n.example.com/webhook/goodjob-trigger', token='secret')
    with client:
        assert client.post('/api/v1/scrape/trigger').status_code == 401
        headers = {'X-Scrape-Token': 'secret'}
        assert client.post('/api/v1/scrape/trigger', headers=headers | {'Origin': 'https://other.example'}).status_code == 403
        assert client.post('/api/v1/scrape/trigger', headers=headers).status_code == 202
        limited = client.post('/api/v1/scrape/trigger', headers=headers)
        assert limited.status_code == 429 and int(limited.headers['retry-after']) > 0


def test_upstream_trigger_failure():
    client, _ = setup_client(webhook='https://n8n.example.com/webhook/test', upstream_status=500)
    with client:
        assert client.post('/api/v1/scrape/trigger').status_code == 502


def test_database_outage_is_visible():
    client, _ = setup_client(unavailable=True)
    with client:
        assert client.get('/api/v1/health').status_code == 503
        assert client.get('/api/v1/metrics/summary').status_code == 503
        assert client.get('/').status_code == 503


def test_production_requires_access_token():
    with pytest.raises(ValueError, match='APP_TRIGGER_TOKEN'):
        Settings(_env_file=None, supabase_url='https://test.supabase.co', supabase_key='x', app_env='production')
