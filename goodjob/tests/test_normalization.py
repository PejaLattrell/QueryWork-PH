from datetime import datetime, timezone

import pytest

from app.models.schemas import Job
from ingestion.normalize import classify, normalize_job, parse_salary, seniority, skills_from


@pytest.mark.parametrize(('salary', 'rates', 'annual'), [
    ('USD 120k - 160k per year', {}, 140000),
    ('$120-160k', {}, 140000),
    ('$50 - $70 /hr', {}, 124800),
    ('PHP 100,000 - 140,000 /month', {'PHP': 0.017}, 24480),
    ('EUR 60000-80000', {}, None),
    ('competitive', {}, None),
    ('100-150', {}, None),
])
def test_salary_periods_and_unknown_currency_rates(salary, rates, annual):
    assert parse_salary(salary, rates)['salary_annual_usd'] == annual


def test_skill_aliases_and_token_boundaries():
    skills = skills_from('JavaScript, Next.js, Node.js, PostgreSQL, C++, C# and Python. Dockerized services.')
    assert {'javascript', 'nextjs', 'nodejs', 'postgresql', 'c++', 'c#', 'python'} <= set(skills)
    assert 'java' not in skills and 'docker' not in skills
    assert classify('Senior Data Platform Engineer') == 'Data Engineer'
    assert classify('Senior Machine Learning Engineer') == 'AI/ML Engineer'
    assert seniority('Principal Backend Engineer') == 'Lead/Principal'


def test_stable_source_identity_preserves_distinct_vacancies_and_updates():
    raw = dict(external_id='first-job', title='Python Developer', company_name='Example', job_url='https://jobs.invalid/job',
               posted_at='2026-01-01T00:00:00Z', description='<script>secret()</script><p>Python &amp; FastAPI</p>',
               location_raw='Philippines', country='PH', work_arrangement='Remote')
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    original = normalize_job(raw, 'fixture-source', now=now)
    updated = normalize_job(raw | {'title': 'Senior Python Developer'}, 'fixture-source', now=now)
    distinct = normalize_job(raw | {'external_id': 'second-job'}, 'fixture-source', now=now)
    assert original['fingerprint'] == updated['fingerprint']
    assert original['fingerprint'] != distinct['fingerprint']
    assert original['country'] == 'PH'
    assert original['description_snippet'] == 'Python & FastAPI'
    assert normalize_job(raw | {'job_url': 'javascript:alert(1)'}, 'fixture-source', now=now) is None
    assert normalize_job(raw | {'posted_at': 'invalid'}, 'fixture-source', now=now) is None
    assert normalize_job(raw | {'posted_at': '2099-01-01T00:00:00Z'}, 'fixture-source', now=now) is None


def test_unknown_salary_rate_preserves_raw_bounds_without_inventing_conversion():
    salary = parse_salary('EUR 60000-80000')
    assert salary == dict(salary_min=60000, salary_max=80000, salary_currency='EUR', salary_annual_usd=None)


@pytest.mark.parametrize('url', [
    'https://jobs.invalid:bad/job', 'https://jobs.invalid:99999/job',
    'https://exa mple.com/job', 'https://user:password@example.com/job',
    'ftp://example.com/job',
])
def test_urls_rejected_by_serving_schema_cannot_be_published(url):
    raw = dict(external_id='developer', title='Developer', company_name='Example', job_url=url, posted_at='2026-01-01T00:00:00Z')
    assert normalize_job(raw, 'fixture-source') is None


@pytest.mark.parametrize('logo', [
    'https://jobs.invalid:bad/logo.png', 'https://jobs.invalid:99999/logo.png',
    'https://exa mple.com/logo.png', 'https://user:password@example.com/logo.png',
])
def test_invalid_optional_logo_does_not_break_otherwise_valid_listing(logo):
    raw = dict(external_id='developer', title='Developer', company_name='Example', job_url='https://jobs.invalid/job',
               company_logo_url=logo, posted_at='2026-01-01T00:00:00Z')
    row = normalize_job(raw, 'fixture-source')
    assert row is not None and row['company_logo_url'] is None


def test_valid_urls_are_canonicalized_for_database_and_serving_models():
    raw = dict(external_id='developer', title='Developer', company_name='Example', job_url='HTTPS://Jobs.INVALID',
               company_logo_url='HTTPS://Jobs.INVALID/logo.png', posted_at='2026-01-01T00:00:00Z')
    row = normalize_job(raw, 'fixture-source')
    assert row['job_url'] == 'https://jobs.invalid/'
    assert row['company_logo_url'] == 'https://jobs.invalid/logo.png'
    validated = Job.model_validate(row | {'id': '00000000-0000-0000-0000-000000000001'})
    assert str(validated.job_url) == row['job_url']


def test_canonical_records_need_a_nonempty_source_identity():
    raw = dict(external_id='developer', title='Developer', company_name='Example', job_url='https://jobs.invalid/job',
               posted_at='2026-01-01T00:00:00Z', location_raw='Philippines', country='PH', work_arrangement='Remote')
    assert normalize_job(raw, '') is None


@pytest.mark.parametrize('arrangement', ['Remote', 'Hybrid', 'On-site', 'Unspecified'])
def test_work_arrangement_uses_explicit_canonical_field(arrangement):
    raw = dict(external_id='developer', title='Developer', company_name='Example', job_url='https://jobs.invalid/job',
               posted_at='2026-01-01T00:00:00Z', location_raw='Philippines', work_arrangement=arrangement)
    assert normalize_job(raw, 'fixture-source')['work_arrangement'] == arrangement


def test_missing_arrangement_is_unspecified_and_naive_publication_time_is_rejected():
    raw = dict(external_id='developer', title='Developer', company_name='Example', job_url='https://jobs.invalid/job',
               posted_at='2026-01-01T00:00:00Z', location_raw='Philippines')
    assert normalize_job(raw, 'fixture-source')['work_arrangement'] == 'Unspecified'
    assert normalize_job(raw | {'posted_at': '2026-01-01'}, 'fixture-source') is None
