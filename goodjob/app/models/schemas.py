from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator

ROLES = ['Backend Engineer', 'Fullstack Engineer', 'Data Engineer', 'AI/ML Engineer', 'DevOps/Cloud', 'Frontend Engineer', 'Other']
Arrangement = Literal['Remote', 'Hybrid', 'On-site', 'Unspecified']


class Filters(BaseModel):
    days: int = Field(30, ge=1, le=365)
    role: str | None = Field(None, max_length=80)
    skill: str | None = Field(None, max_length=60)
    work_arrangement: Arrangement | None = None
    search: str | None = Field(None, max_length=200)
    min_salary: float | None = Field(None, ge=0, le=1e9)

    @field_validator('role', 'skill', 'work_arrangement', 'search', 'min_salary', mode='before')
    @classmethod
    def normalize_empty(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator('skill')
    @classmethod
    def canonical_skill(cls, value):
        return value.lower() if value else None

    def rpc_params(self):
        return {'p_' + k: v for k, v in self.model_dump().items() if k in Filters.model_fields}


class JobsQuery(Filters):
    page: int = Field(1, ge=1, le=100000)
    limit: int = Field(15, ge=1, le=100)


class Job(BaseModel):
    id: UUID
    external_id: str
    fingerprint: str
    title: str
    company_name: str
    normalized_role: str
    company_logo_url: HttpUrl | None = None
    location_raw: str | None = None
    country: str | None = None
    work_arrangement: Arrangement
    employment_type: str | None = None
    seniority_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_annual_usd: float | None = None
    skills: list[str]
    description_snippet: str | None = None
    job_url: HttpUrl
    source: str
    posted_at: datetime
    scraped_at: datetime
    is_active: bool


class SkillDemand(BaseModel):
    skill: str
    mention_count: int
    avg_salary_usd: float | None = None


class CompanyDemand(BaseModel):
    company_name: str
    job_count: int


class Summary(BaseModel):
    total_jobs: int
    jobs_added_last_24h: int
    avg_annual_salary_usd: float | None = None
    median_annual_salary_usd: float | None = None
    salary_sample_size: int = 0
    seed_job_count: int = 0
    remote_percentage: float
    top_hiring_companies: list[CompanyDemand]
    top_skill: SkillDemand | None = None
    last_scrape_at: datetime | None = None


class DailyVolume(BaseModel):
    post_date: str
    normalized_role: str
    job_count: int


class SalaryBenchmark(BaseModel):
    normalized_role: str
    seniority_level: str | None = None
    job_count: int
    min_salary: float
    avg_salary: float
    median_salary: float
    max_salary: float


class ArrangementSplit(BaseModel):
    work_arrangement: Arrangement
    job_count: int
    percentage: float


class Trends(BaseModel):
    daily_volume: list[DailyVolume]
    top_skills: list[SkillDemand]
    salary_benchmarks: list[SalaryBenchmark]
    work_arrangements: list[ArrangementSplit]


class JobsPage(BaseModel):
    items: list[Job]
    total: int
    page: int
    limit: int

    @property
    def pages(self):
        return max(1, (self.total + self.limit - 1) // self.limit)


class TriggerResponse(BaseModel):
    status: Literal['accepted', 'not_configured']
    message: str
    triggered_at: datetime | None = None


class IngestionStatus(BaseModel):
    status: Literal['idle', 'running', 'completed', 'failed', 'not_configured']
    run_id: str | None = None
    jobs_found: int = 0
    jobs_upserted: int = 0
    rejected: int = 0
    message: str
