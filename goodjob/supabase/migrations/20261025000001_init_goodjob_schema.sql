begin;
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.scrape_runs (
  id uuid primary key default gen_random_uuid(), source text not null,
  status text not null check (status in ('running','completed','failed')),
  jobs_found integer not null default 0 check(jobs_found >= 0),
  jobs_upserted integer not null default 0 check(jobs_upserted >= 0),
  error_message text, started_at timestamptz not null default now(), completed_at timestamptz
);
create table if not exists public.job_postings (
  id uuid primary key default gen_random_uuid(), external_id text not null,
  fingerprint text not null unique check(fingerprint ~ '^[a-f0-9]{64}$'),
  title text not null, normalized_role text not null, company_name text not null,
  company_logo_url text, location_raw text, country text,
  work_arrangement text not null default 'Remote' check(work_arrangement in ('Remote','Hybrid','On-site','Unspecified')),
  employment_type text default 'Full-time',
  seniority_level text default 'Mid-Level' check(seniority_level in ('Intern/Junior','Mid-Level','Senior','Lead/Principal','Unspecified')),
  salary_min numeric(12,2), salary_max numeric(12,2), salary_currency varchar(10) default 'USD',
  salary_annual_usd numeric(12,2), skills text[] not null default '{}',
  description_snippet text, job_url text not null check(job_url ~ '^https?://'), source text not null,
  posted_at timestamptz not null, scraped_at timestamptz not null default now(), is_active boolean not null default true,
  check(salary_min is null or salary_min >= 0), check(salary_max is null or salary_max >= salary_min),
  check(salary_annual_usd is null or salary_annual_usd >= 0)
);
create index if not exists job_postings_skills_idx on public.job_postings using gin(skills);
create index if not exists job_postings_posted_idx on public.job_postings(posted_at desc);
create index if not exists job_postings_role_idx on public.job_postings(normalized_role);
create index if not exists job_postings_arrangement_idx on public.job_postings(work_arrangement);
create index if not exists job_postings_source_idx on public.job_postings(source);
create index if not exists job_postings_salary_idx on public.job_postings(salary_annual_usd);
create index if not exists scrape_runs_completed_idx on public.scrape_runs(completed_at desc) where status='completed';

alter table public.job_postings enable row level security;
alter table public.scrape_runs enable row level security;
revoke all on public.job_postings,public.scrape_runs from anon,authenticated;
grant select on public.job_postings to anon,authenticated;
grant select(id,source,status,jobs_found,jobs_upserted,started_at,completed_at) on public.scrape_runs to anon,authenticated;
grant all on public.job_postings,public.scrape_runs to service_role;
drop policy if exists goodjob_public_jobs on public.job_postings;
create policy goodjob_public_jobs on public.job_postings for select to anon,authenticated using(true);
drop policy if exists goodjob_public_run_status on public.scrape_runs;
create policy goodjob_public_run_status on public.scrape_runs for select to anon,authenticated using(true);

create or replace view public.vw_daily_job_volume with(security_invoker=true) as
select (posted_at at time zone 'UTC')::date post_date, normalized_role,count(*) job_count
from public.job_postings where is_active and posted_at >= now()-interval '30 days'
group by 1,2;
create or replace view public.vw_top_skills_demand with(security_invoker=true) as
select skill,count(*) mention_count,round(avg(salary_annual_usd),2) avg_salary_usd
from public.job_postings cross join lateral unnest(skills) skill
where is_active and posted_at >= now()-interval '30 days'
group by skill order by mention_count desc,skill limit 25;
create or replace view public.vw_role_salary_benchmarks with(security_invoker=true) as
select normalized_role,seniority_level,count(*) job_count,min(salary_annual_usd) min_salary,
round(avg(salary_annual_usd),2) avg_salary,percentile_cont(0.5) within group(order by salary_annual_usd) median_salary,
max(salary_annual_usd) max_salary from public.job_postings
where is_active and salary_annual_usd is not null group by 1,2;
create or replace view public.vw_work_arrangement_split with(security_invoker=true) as
select a.work_arrangement,count(j.id) job_count,
round(100.0*count(j.id)/nullif(sum(count(j.id)) over(),0),2) percentage
from unnest(array['Remote','Hybrid','On-site','Unspecified']) a(work_arrangement)
left join public.job_postings j on j.work_arrangement=a.work_arrangement and j.is_active group by 1;
grant select on public.vw_daily_job_volume,public.vw_top_skills_demand,public.vw_role_salary_benchmarks,public.vw_work_arrangement_split to anon,authenticated,service_role;

create or replace function public.goodjob_filtered_jobs(
 p_days int default 30,p_role text default null,p_skill text default null,
 p_work_arrangement text default null,p_search text default null,p_min_salary numeric default null)
returns setof public.job_postings language sql stable security invoker set search_path='' as $$
select j.* from public.job_postings j where j.is_active
 and j.posted_at >= now()-make_interval(days=>greatest(1,least(p_days,365))) and j.posted_at <= now()
 and (p_role is null or j.normalized_role=p_role)
 and (p_skill is null or j.skills @> array[lower(trim(p_skill))])
 and (p_work_arrangement is null or j.work_arrangement=p_work_arrangement)
 and (p_search is null or strpos(lower(j.title||' '||j.company_name),lower(p_search))>0)
 and (p_min_salary is null or j.salary_annual_usd>=p_min_salary);
$$;
create or replace function public.get_dashboard_summary(
 p_days int default 30,p_role text default null,p_skill text default null,
 p_work_arrangement text default null,p_search text default null,p_min_salary numeric default null)
returns jsonb language sql stable security invoker set search_path='' as $$
with f as materialized(select * from public.goodjob_filtered_jobs(p_days,p_role,p_skill,p_work_arrangement,p_search,p_min_salary)),
 companies as(select company_name,count(*) job_count from f group by 1 order by 2 desc,1 limit 5),
 skills as(select skill,count(*) mention_count from f cross join lateral unnest(skills) skill group by 1 order by 2 desc,1 limit 1)
select jsonb_build_object('total_jobs',count(*),'jobs_added_last_24h',count(*) filter(where posted_at>=now()-interval '24 hours'),
 'avg_annual_salary_usd',round(avg(salary_annual_usd),2),'median_annual_salary_usd',percentile_cont(0.5) within group(order by salary_annual_usd),
 'salary_sample_size',count(salary_annual_usd),'seed_job_count',count(*) filter(where source='seed'),
 'remote_percentage',coalesce(round(100.0*count(*) filter(where work_arrangement='Remote')/nullif(count(*),0),1),0),
 'top_hiring_companies',coalesce((select jsonb_agg(to_jsonb(companies)) from companies),'[]'::jsonb),
 'top_skill',(select to_jsonb(s) from skills s),
 'last_scrape_at',(select max(completed_at) from public.scrape_runs where status='completed')) from f;
$$;
create or replace function public.get_dashboard_trends(
 p_days int default 30,p_role text default null,p_skill text default null,
 p_work_arrangement text default null,p_search text default null,p_min_salary numeric default null)
returns jsonb language sql stable security invoker set search_path='' as $$
with f as materialized(select * from public.goodjob_filtered_jobs(p_days,p_role,p_skill,p_work_arrangement,p_search,p_min_salary)),
 daily as(select (posted_at at time zone 'UTC')::date post_date,normalized_role,count(*) job_count from f group by 1,2 order by 1,2),
 skills as(select skill,count(*) mention_count,round(avg(salary_annual_usd),2) avg_salary_usd from f cross join lateral unnest(skills) skill group by 1 order by 2 desc,1 limit 25),
 salary as(select normalized_role,seniority_level,count(*) job_count,min(salary_annual_usd) min_salary,round(avg(salary_annual_usd),2) avg_salary,
 percentile_cont(0.5) within group(order by salary_annual_usd) median_salary,max(salary_annual_usd) max_salary from f where salary_annual_usd is not null group by 1,2 order by 1,2),
 arrangements as(select a.work_arrangement,count(f.id) job_count,coalesce(round(100.0*count(f.id)/nullif(sum(count(f.id)) over(),0),1),0) percentage
 from unnest(array['Remote','Hybrid','On-site','Unspecified']) a(work_arrangement) left join f using(work_arrangement) group by 1)
select jsonb_build_object('daily_volume',coalesce((select jsonb_agg(to_jsonb(daily)) from daily),'[]'::jsonb),
 'top_skills',coalesce((select jsonb_agg(to_jsonb(skills)) from skills),'[]'::jsonb),
 'salary_benchmarks',coalesce((select jsonb_agg(to_jsonb(salary)) from salary),'[]'::jsonb),
 'work_arrangements',coalesce((select jsonb_agg(to_jsonb(arrangements)) from arrangements),'[]'::jsonb));
$$;
create or replace function public.get_jobs(
 p_days int default 30,p_role text default null,p_skill text default null,p_work_arrangement text default null,
 p_search text default null,p_min_salary numeric default null,p_page int default 1,p_limit int default 15)
returns jsonb language sql stable security invoker set search_path='' as $$
with f as materialized(select * from public.goodjob_filtered_jobs(p_days,p_role,p_skill,p_work_arrangement,p_search,p_min_salary)),
 paged as(select * from f order by posted_at desc,id limit greatest(1,least(p_limit,100)) offset (greatest(p_page,1)::bigint-1)*greatest(1,least(p_limit,100)))
select jsonb_build_object('items',coalesce((select jsonb_agg(to_jsonb(paged)) from paged),'[]'::jsonb),
 'total',(select count(*) from f),'page',greatest(p_page,1),'limit',greatest(1,least(p_limit,100)));
$$;
revoke all on function public.goodjob_filtered_jobs(int,text,text,text,text,numeric),public.get_dashboard_summary(int,text,text,text,text,numeric),public.get_dashboard_trends(int,text,text,text,text,numeric),public.get_jobs(int,text,text,text,text,numeric,int,int) from public;
grant execute on function public.goodjob_filtered_jobs(int,text,text,text,text,numeric),public.get_dashboard_summary(int,text,text,text,text,numeric),public.get_dashboard_trends(int,text,text,text,text,numeric),public.get_jobs(int,text,text,text,text,numeric,int,int) to anon,authenticated,service_role;

-- Illustrative data, explicitly marked as seed; these are not verified vacancies.
with seed(title,normalized_role,company_name,location_raw,country,work_arrangement,seniority_level,lo,hi,skills,age) as(values
 ('Senior Backend Engineer','Backend Engineer','Northstar Labs','United States','US','Remote','Senior',145000,185000,array['python','fastapi','postgresql','docker'],0),
 ('Backend Platform Engineer','Backend Engineer','Orbit Systems','Berlin, Germany','DE','Hybrid','Mid-Level',95000,125000,array['java','kafka','postgresql','kubernetes'],1),
 ('Junior Python Developer','Backend Engineer','Cedar Software','London, UK','GB','On-site','Intern/Junior',55000,75000,array['python','django','postgresql'],2),
 ('Lead API Engineer','Backend Engineer','Harbor Cloud','Canada','CA','Remote','Lead/Principal',170000,210000,array['typescript','nodejs','redis','aws'],3),
 ('Senior Data Engineer','Data Engineer','Meridian Data','United States','US','Remote','Senior',155000,195000,array['python','airflow','kafka','snowflake'],0),
 ('Analytics Data Engineer','Data Engineer','Juniper Analytics','Singapore','SG','Hybrid','Mid-Level',100000,135000,array['python','dbt','bigquery','sql'],4),
 ('Data Platform Engineer','Data Engineer','Tidal Insights','Amsterdam, Netherlands','NL','On-site','Mid-Level',95000,130000,array['python','spark','kafka','docker'],5),
 ('Principal Data Engineer','Data Engineer','Atlas Research','Worldwide',null,'Remote','Lead/Principal',185000,225000,array['python','airflow','snowflake','aws'],6),
 ('Fullstack Product Engineer','Fullstack Engineer','Meadow Studio','Worldwide',null,'Remote','Mid-Level',110000,145000,array['typescript','nextjs','react','supabase'],1),
 ('Senior Fullstack Engineer','Fullstack Engineer','Beacon Apps','Australia','AU','Hybrid','Senior',135000,175000,array['typescript','react','nodejs','postgresql'],2),
 ('Fullstack Engineer','Fullstack Engineer','Copper Works','Manila, Philippines','PH','On-site','Mid-Level',35000,55000,array['php','laravel','mysql','javascript'],7),
 ('Lead Fullstack Engineer','Fullstack Engineer','Prism Digital','United States','US','Remote','Lead/Principal',165000,205000,array['nextjs','supabase','typescript','docker'],8),
 ('Senior Machine Learning Engineer','AI/ML Engineer','Aurora AI','United States','US','Remote','Senior',175000,225000,array['python','pytorch','fastapi','aws'],1),
 ('AI Application Engineer','AI/ML Engineer','Quill Intelligence','London, UK','GB','Hybrid','Mid-Level',115000,155000,array['python','langchain','postgresql','docker'],3),
 ('ML Research Engineer','AI/ML Engineer','Summit Models','Toronto, Canada','CA','On-site','Senior',150000,200000,array['python','pytorch','tensorflow','kubernetes'],9),
 ('Junior AI Engineer','AI/ML Engineer','Sprout AI','Worldwide',null,'Remote','Intern/Junior',70000,95000,array['python','scikit-learn','fastapi'],10),
 ('Senior DevOps Engineer','DevOps/Cloud','Stratus Infra','United States','US','Remote','Senior',150000,190000,array['docker','kubernetes','terraform','aws'],2),
 ('Cloud Reliability Engineer','DevOps/Cloud','Willow Networks','Germany','DE','Hybrid','Mid-Level',100000,140000,array['gcp','terraform','prometheus','linux'],11),
 ('Platform Engineer','DevOps/Cloud','Granite Cloud','Worldwide',null,'Remote','Mid-Level',120000,160000,array['docker','kubernetes','github actions','python'],12),
 ('Principal SRE','DevOps/Cloud','Lumen Systems','United States','US','Remote','Lead/Principal',190000,235000,array['aws','kubernetes','golang','prometheus'],13)
)
insert into public.job_postings(external_id,fingerprint,title,normalized_role,company_name,location_raw,country,work_arrangement,seniority_level,salary_min,salary_max,salary_annual_usd,skills,description_snippet,job_url,source,posted_at)
select 'seed-'||row_number() over(),encode(extensions.digest(lower(company_name)||'::'||lower(title)||'::seed','sha256'),'hex'),
title,normalized_role,company_name,location_raw,country,work_arrangement,seniority_level,lo,hi,(lo+hi)/2,skills,
'Illustrative seed posting for dashboard exploration. This is not a verified vacancy.','https://example.com','seed',now()-make_interval(days=>age)-interval '1 hour' from seed
on conflict(fingerprint) do nothing;
notify pgrst,'reload schema';
commit;
