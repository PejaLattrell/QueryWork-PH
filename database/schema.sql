create table public.job_sources (
  id text primary key check (id in ('remotive','jobicy')),
  name text not null, website text not null,
  last_started_at timestamptz, last_success_at timestamptz,
  lease_until timestamptz
);
insert into public.job_sources(id,name,website) values
 ('remotive','Remotive','https://remotive.com'),('jobicy','Jobicy','https://jobicy.com');

create table public.collection_runs (
  id uuid primary key default gen_random_uuid(),
  source text not null references public.job_sources(id),
  started_at timestamptz not null default now(), finished_at timestamptz,
  status text not null default 'running' check(status in ('running','success','partial','failed')),
  fetched integer not null default 0, stored integer not null default 0,
  rejected integer not null default 0, pages integer not null default 0,
  truncated boolean not null default false, error text
);
create index collection_runs_started_idx on public.collection_runs(started_at desc);
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  source text not null references public.job_sources(id), source_job_id text not null,
  title text not null, company text not null, location text not null default 'Not specified',
  category text not null default 'Other', employment_type text not null default 'Not specified',
  salary text, description text not null default '', url text not null check(url ~ '^https://'),
  tags text[] not null default '{}', duplicate_key text not null,
  published_at timestamptz, first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique(source,source_job_id)
);
create index jobs_published_idx on public.jobs(published_at desc nulls last);
create index jobs_duplicate_idx on public.jobs(duplicate_key);
create index jobs_last_seen_idx on public.jobs(last_seen_at desc);
create table public.job_payloads (
  source text not null, source_job_id text not null,
  run_id uuid not null references public.collection_runs(id),
  payload jsonb not null, captured_at timestamptz not null default now(),
  primary key (source,source_job_id),
  foreign key (source,source_job_id) references public.jobs(source,source_job_id)
);
create index job_payloads_run_idx on public.job_payloads(run_id);

alter table public.jobs enable row level security;
alter table public.job_sources enable row level security;
alter table public.collection_runs enable row level security;
alter table public.job_payloads enable row level security;
revoke all on public.jobs,public.job_sources,public.collection_runs,public.job_payloads from anon,authenticated;
grant select on public.jobs,public.job_sources,public.collection_runs to anon,authenticated;
grant select,insert,update,delete on public.jobs,public.job_sources,public.collection_runs,public.job_payloads to service_role;
create policy "Public job listings" on public.jobs for select to anon,authenticated using (true);
create policy "Public source health" on public.job_sources for select to anon,authenticated using (true);
create policy "Public collection history" on public.collection_runs for select to anon,authenticated using (true);

create function public.claim_job_collection(p_source text) returns uuid
language plpgsql security invoker set search_path = '' as $$
declare v_run uuid;
begin
  update public.job_sources set lease_until=now()+interval '4 minutes',last_started_at=now()
  where id=p_source and (lease_until is null or lease_until<now())
    and (last_started_at is null or last_started_at<now()-interval '30 minutes')
    and (last_success_at is null or last_success_at<now()-interval '6 hours');
  if not found then return null; end if;
  update public.collection_runs set status='failed',finished_at=now(),error='Collection lease expired'
    where source=p_source and status='running' and started_at<now()-interval '4 minutes';
  insert into public.collection_runs(source) values(p_source) returning id into v_run;
  return v_run;
end; $$;
revoke all on function public.claim_job_collection(text) from public,anon,authenticated;
grant execute on function public.claim_job_collection(text) to service_role;
