-- STRIX cloud persistence — core durable research-job schema.
--
-- `research_jobs` is the single durable unit of work the hosted API reads and
-- writes (see strix.jobs.supabase_store). It is written before execution begins
-- and carries all state between stateless serverless invocations: lifecycle
-- status, execution lease, bounded-retry attempt count, progress log, recovery
-- checkpoint, and the structured result (answer, independently-verified claims,
-- evidence, SHA-256 manifest, usage) as JSONB. Raw evidence bytes and the full
-- replay bundle live in private object storage (see 0002_storage.sql).
--
-- Row-level security scopes every row to its owner (auth.users). The API
-- connects with the service role (which bypasses RLS) and ALSO enforces
-- ownership in every query; RLS is defense-in-depth for any Data-API access.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- research_jobs
-- ---------------------------------------------------------------------------
create table if not exists public.research_jobs (
    id                text primary key,
    user_id           uuid not null references auth.users (id) on delete cascade,
    question          text not null check (char_length(question) between 1 and 2000),
    as_of             text,
    status            text not null default 'queued'
                          check (status in (
                              'queued', 'running', 'completed',
                              'partial', 'failed', 'cancelled', 'timed_out'
                          )),
    idempotency_key   text not null,
    attempt           integer not null default 0 check (attempt >= 0),
    max_attempts      integer not null default 2 check (max_attempts >= 1),
    cancel_requested  boolean not null default false,

    -- execution lease (duplicate-execution protection + stale detection)
    lease_owner       text,
    lease_expires_at  timestamptz,
    deadline_at       timestamptz,

    -- progress / recovery / output
    progress          jsonb not null default '[]'::jsonb,
    checkpoint        jsonb,
    run_id            text,
    result            jsonb,
    error             text,
    cost_usd          text,

    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    started_at        timestamptz,
    finished_at       timestamptz,

    -- idempotent submission: one job per (user, key)
    constraint research_jobs_user_idempotency_key unique (user_id, idempotency_key)
);

create index if not exists idx_research_jobs_user_created
    on public.research_jobs (user_id, created_at desc);
create index if not exists idx_research_jobs_status
    on public.research_jobs (status);
create index if not exists idx_research_jobs_run_id
    on public.research_jobs (run_id) where run_id is not null;
-- Sweeper lookup: queued, or running with an expired lease.
create index if not exists idx_research_jobs_lease
    on public.research_jobs (status, lease_expires_at);

-- keep updated_at honest even for direct SQL writes
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_research_jobs_touch on public.research_jobs;
create trigger trg_research_jobs_touch
    before update on public.research_jobs
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- Row-level security: owner-only access.
-- ---------------------------------------------------------------------------
alter table public.research_jobs enable row level security;

drop policy if exists research_jobs_select_own on public.research_jobs;
create policy research_jobs_select_own on public.research_jobs
    for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists research_jobs_insert_own on public.research_jobs;
create policy research_jobs_insert_own on public.research_jobs
    for insert to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists research_jobs_update_own on public.research_jobs;
create policy research_jobs_update_own on public.research_jobs
    for update to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

-- No DELETE policy: users cannot delete research history (immutable audit).

-- ---------------------------------------------------------------------------
-- research_runs — completed runs, as a security-invoker view over the base
-- table so RLS is inherited and there is no duplicate write path.
-- ---------------------------------------------------------------------------
create or replace view public.research_runs
with (security_invoker = true) as
select
    run_id,
    id as job_id,
    user_id,
    question,
    status,
    cost_usd,
    result -> 'answer'   as answer,
    result -> 'usage'    as usage,
    result -> 'manifest' as manifest,
    created_at,
    finished_at
from public.research_jobs
where run_id is not null
  and status in ('completed', 'partial');

-- ---------------------------------------------------------------------------
-- cost_accounting — per-user daily spend, security-invoker view (RLS applies).
-- ---------------------------------------------------------------------------
create or replace view public.cost_accounting
with (security_invoker = true) as
select
    user_id,
    date_trunc('day', created_at) as day,
    count(*)                       as job_count,
    coalesce(sum(cost_usd::numeric), 0) as total_cost_usd
from public.research_jobs
group by user_id, date_trunc('day', created_at);
