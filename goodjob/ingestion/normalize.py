"""Validate source-neutral canonical job records and prepare serving rows.

Future explicitly selected adapters must map their records into this contract.
This module contains no production source adapter or endpoint.
"""

import hashlib
import html
import math
import re
from datetime import datetime, timezone

from pydantic import HttpUrl, TypeAdapter, ValidationError


SKILLS = {
    'python': 'python', 'java': 'java', 'javascript': 'javascript|ecmascript',
    'typescript': 'typescript', 'php': 'php', 'ruby': 'ruby', 'rust': 'rust',
    'golang': 'golang|go language', 'scala': 'scala', 'kotlin': 'kotlin', 'swift': 'swift',
    'c++': r'c\+\+', 'c#': 'c#|c sharp', 'react': r'react(?:\.js)?',
    'nextjs': r'next\.?js', 'vue': r'vue(?:\.js)?', 'angular': 'angular',
    'svelte': 'svelte', 'fastapi': 'fastapi', 'django': 'django', 'flask': 'flask',
    'laravel': 'laravel', 'nodejs': r'node\.?js', 'express': r'express\.?js',
    'spring': 'spring boot', 'rails': 'rails', 'postgresql': 'postgres(?:ql)?',
    'supabase': 'supabase', 'mysql': 'mysql', 'mongodb': 'mongo(?:db)?',
    'docker': 'docker', 'kubernetes': 'kubernetes|k8s', 'aws': 'aws|amazon web services',
    'gcp': 'gcp|google cloud', 'azure': 'azure', 'kafka': 'kafka', 'airflow': 'airflow',
    'snowflake': 'snowflake', 'bigquery': 'bigquery', 'graphql': 'graphql', 'redis': 'redis',
    'pytorch': 'pytorch', 'tensorflow': 'tensorflow', 'scikit-learn': 'scikit[ -]learn',
    'spark': 'apache spark|pyspark', 'dbt': 'dbt', 'sql': 'sql', 'terraform': 'terraform',
    'ansible': 'ansible', 'linux': 'linux', 'prometheus': 'prometheus', 'grafana': 'grafana',
    'elasticsearch': 'elasticsearch', 'github actions': 'github actions', 'git': 'git',
    'langchain': 'langchain', 'pandas': 'pandas', 'numpy': 'numpy', 'tailwind': 'tailwind',
    'html': 'html5?', 'css': 'css3?', 'rest api': 'rest(?:ful)? api', 'databricks': 'databricks',
}
_SKILL_PATTERNS = [(key, re.compile(r'(?:^|[^a-z0-9])(?:' + value + r')(?=$|[^a-z0-9])', re.I))
                   for key, value in SKILLS.items()]
_HTTP_URL = TypeAdapter(HttpUrl)


def clean(value) -> str:
    text = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', ' ', str(value or ''), flags=re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', text))).strip()


def skills_from(text: str) -> list[str]:
    return [key for key, pattern in _SKILL_PATTERNS if pattern.search(text)]


def classify(title: str) -> str:
    patterns = [
        (r'data engineer|analytics engineer|data platform|etl|data architect', 'Data Engineer'),
        (r'machine learning|\bml\b|\bai\b|artificial intelligence|data scientist', 'AI/ML Engineer'),
        (r'devops|sre\b|site reliability|cloud|infrastructure|platform engineer', 'DevOps/Cloud'),
        (r'full[ -]?stack', 'Fullstack Engineer'),
        (r'front[ -]?end|\breact\b|\bvue\b|\bui engineer', 'Frontend Engineer'),
        (r'back[ -]?end|\bapi\b|python|java\b|node\.?js|php|software engineer', 'Backend Engineer'),
    ]
    return next((role for pattern, role in patterns if re.search(pattern, title, re.I)), 'Other')


def seniority(title: str) -> str:
    if re.search(r'lead|principal|staff|head of|architect', title, re.I):
        return 'Lead/Principal'
    if re.search(r'senior|\bsr\.?\b', title, re.I):
        return 'Senior'
    if re.search(r'junior|\bjr\.?\b|intern|entry[ -]level|graduate', title, re.I):
        return 'Intern/Junior'
    return 'Mid-Level'


def parse_salary(raw, rates: dict[str, float] | None = None) -> dict:
    text = clean(raw).upper()
    empty = dict(salary_min=None, salary_max=None, salary_currency=None, salary_annual_usd=None)
    if not text or re.search('COMPETITIVE|UNDISCLOSED|NEGOTIABLE', text):
        return empty
    match = re.search(r'\b(USD|EUR|GBP|CAD|AUD|PHP|INR|SGD)\b', text)
    currency = match.group(1) if match else next((code for pattern, code in [
        (r'\bCA?\$', 'CAD'), (r'\bAU?\$', 'AUD'), (r'\bSG?\$', 'SGD'),
        ('€', 'EUR'), ('£', 'GBP'), (r'US\$|\$', 'USD')
    ] if re.search(pattern, text)), None)
    matches = list(re.finditer(r'\d[\d,]*(?:\.\d+)?\s*K?', text))
    if not currency or not 1 <= len(matches) <= 2:
        return empty
    values = [float(re.sub(r'[,K\s]', '', m.group())) * (1000 if 'K' in m.group() else 1)
              for m in matches]
    if len(values) == 2 and 'K' in matches[1].group() and 'K' not in matches[0].group() and values[0] < 1000:
        values[0] *= 1000
    lo, hi = min(values), max(values)
    factor = next((factor for pattern, factor in [
        (r'HOUR|/HR|/H\b', 2080), (r'MONTH|/MO\b', 12),
        (r'WEEK|/WK\b', 52), (r'DAY|/D\b', 260)
    ] if re.search(pattern, text)), 1)
    if lo <= 0 or hi > 10_000_000 or (factor == 1 and hi < 1000 and not re.search(r'YEAR|ANNUAL|/YR', text)):
        return empty
    try:
        rate = 1.0 if currency == 'USD' else float((rates or {}).get(currency, 0))
    except (ValueError, TypeError):
        rate = 0
    annual = round((lo + hi) / 2 * factor * rate, 2) if math.isfinite(rate) and rate > 0 else None
    if annual is not None and not 0 < annual < 10_000_000_000:
        annual = None
    return dict(salary_min=lo, salary_max=hi, salary_currency=currency, salary_annual_usd=annual)


def http_url(value) -> str | None:
    """Return the same canonical HTTP URL shape accepted by the serving models."""
    if not isinstance(value, str):
        return None
    try:
        parsed = _HTTP_URL.validate_python(value)
        if parsed.username is not None or parsed.password is not None:
            return None
        return str(parsed)
    except ValidationError:
        return None


def normalize_job(job: dict, source: str, rates: dict | None = None, *, now: datetime | None = None) -> dict | None:
    if not isinstance(source, str) or not source.strip() or not isinstance(job, dict):
        return None
    title, company = clean(job.get('title')), clean(job.get('company_name'))
    job_url = http_url(job.get('job_url'))
    external_id = job.get('external_id')
    now = now or datetime.now(timezone.utc)
    try:
        posted = datetime.fromisoformat(str(job['posted_at']).replace('Z', '+00:00'))
        if posted.tzinfo is None:
            return None
        posted = posted.astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    if (not title or not company or not isinstance(external_id, (str, int)) or isinstance(external_id, bool)
            or str(external_id) == '' or not job_url or posted > now):
        return None
    description = clean(job.get('description'))
    location = clean(job.get('location_raw'))
    skills = job.get('skills') if isinstance(job.get('skills'), list) else []
    context = ' '.join([title, description, *map(str, skills)])
    arrangement = job.get('work_arrangement', 'Unspecified')
    if not isinstance(arrangement, str) or arrangement not in {'Remote', 'Hybrid', 'On-site', 'Unspecified'}:
        return None
    country = clean(job.get('country')).upper()
    country = country if re.fullmatch('[A-Z]{2}', country) else None
    return dict(
        external_id=str(external_id),
        fingerprint=hashlib.sha256((source + '::' + str(external_id)).encode()).hexdigest(),
        title=title, normalized_role=classify(title), company_name=company,
        company_logo_url=http_url(job.get('company_logo_url')),
        location_raw=location or None, country=country, work_arrangement=arrangement,
        employment_type=clean(job.get('employment_type')) or 'Unspecified',
        seniority_level=seniority(title), **parse_salary(job.get('salary'), rates),
        skills=skills_from(context), description_snippet=description[:700], job_url=job_url,
        source=source, posted_at=posted.isoformat(), scraped_at=now.isoformat(), is_active=True,
    )
