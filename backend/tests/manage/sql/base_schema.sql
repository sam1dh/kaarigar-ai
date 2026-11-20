-- Test-only stand-in for migrations 0001-0004 (the tables Phase 4 reads), plus a tiny auth.users stub.
-- Built from Phase 3's tests/assist/sql/base_schema.sql + 0004_phase3.sql + Phase 1's log_imports.

create table tenants (id uuid primary key default gen_random_uuid(), name text not null, slug text not null unique, city text, created_at timestamptz not null default now());
create table users (id uuid primary key, tenant_id uuid not null references tenants(id), name text not null, employee_id text,
  role text not null check (role in ('technician','expert','supervisor')), is_admin boolean not null default false,
  language text not null default 'hi-IN', created_at timestamptz not null default now(), unique (tenant_id, employee_id));
create table machine_models (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), oem text, model text not null, type text, created_at timestamptz not null default now());
create table machines (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), model_id uuid references machine_models(id),
  code text not null, name text, line text, qr_token text not null unique default encode(gen_random_bytes(12),'hex'), created_at timestamptz not null default now(), unique (tenant_id, code));
create table documents (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), model_id uuid references machine_models(id),
  title text not null, type text not null, file_path text not null, status text not null default 'uploaded', pages int, quality_notes text, error text, file_hash text, created_by uuid, created_at timestamptz not null default now());
create table maintenance_logs (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), machine_id uuid references machines(id), import_id uuid,
  date date, fault text, action text, downtime_min int, technician text, raw jsonb, created_at timestamptz not null default now());
create table symptoms (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, name text not null, aliases text[] not null default '{}', unique(tenant_id,name));
create table causes (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, name text not null, aliases text[] not null default '{}', unique(tenant_id,name));
create table fixes (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, name text not null, aliases text[] not null default '{}', unique(tenant_id,name));
create table repair_records (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), machine_id uuid not null references machines(id),
  author_id uuid not null references users(id), audio_path text, transcript_en text, symptom_id uuid, cause_id uuid, fix_id uuid, safety_note text, fields jsonb, ai_check jsonb,
  status text not null default 'draft' check (status in ('draft','expert_review','pending','approved','rejected')), reject_reason text, reviewed_by uuid references users(id), reviewed_at timestamptz,
  source text not null default 'capture' check (source in ('capture','escalation','seed')), created_at timestamptz not null default now(),
  language text, audio_seconds numeric(6,1), stage text, error text, fields_local jsonb, submitted_at timestamptz, edited_by_expert boolean not null default false, edited_by_reviewer boolean not null default false);
create table chunks (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, source_type text not null, source_id uuid not null, machine_id uuid, model_id uuid,
  section text, text text not null, page int, chunk_index int not null default 0, meta jsonb not null default '{}', created_at timestamptz not null default now());
create table queries (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), user_id uuid not null references users(id), machine_id uuid references machines(id),
  question_original text, question_en text, language text, answer text, confidence real, citations jsonb, escalated boolean not null default false, latency_ms int, created_at timestamptz not null default now());
create table feedback (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), query_id uuid not null references queries(id) on delete cascade,
  user_id uuid not null references users(id), outcome text not null check (outcome in ('fixed','not_fixed','call_supervisor')), created_at timestamptz not null default now());
create table escalations (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), query_id uuid not null references queries(id),
  assigned_to uuid references users(id), status text not null default 'open' check (status in ('open','answered')), reply_text text, reply_audio_path text,
  new_record_id uuid references repair_records(id), created_at timestamptz not null default now(), answered_at timestamptz);
create publication supabase_realtime;
alter publication supabase_realtime add table escalations;

create table log_imports (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id),
  file_name text, file_path text, file_hash text, detected jsonb, mapping jsonb, status text not null default 'uploaded',
  rows_ok int not null default 0, rows_skipped int not null default 0, created_by uuid references users(id), created_at timestamptz not null default now());

create schema if not exists auth;
-- Phase 0 RLS helper (real one reads the tenant from the JWT); enough for policies to be created
create or replace function public.current_tenant_id() returns uuid language sql stable as $$ select null::uuid $$;
create table auth.users (id uuid primary key, email text, last_sign_in_at timestamptz);

-- ===== 0004_phase3.sql (verbatim) =====
-- Kaarigar AI — Phase 3 (Assist + Escalations)
-- Additive and safe to run twice. Run in the Supabase SQL editor after 0003_phase2.sql.
--
-- What it adds
--   queries      : answer status, the answer in the technician's language, the sources shown, timings
--   feedback     : one row per (question, person)  -> "Fixed it" can be changed to "Still broken"
--   escalations  : who asked, machine, note, closed status, cached reply translation, one per question
--   repair_records.escalation_id : an expert's voice reply becomes a normal Capture record linked here
--   trigger      : when that reply is sent to the supervisor (status -> pending), the escalation is
--                  marked answered automatically (no Phase 2 code change needed)
--   realtime     : escalations + repair_records publish changes (badges update without polling)

-- ===================================================================== queries
alter table queries add column if not exists status text not null default 'answered';
alter table queries add column if not exists answer_local text;            -- what the technician saw/heard
alter table queries add column if not exists answer_parts jsonb;           -- parsed {safety[], steps[{text, refs}], check, refs_used[]}
alter table queries add column if not exists sources jsonb not null default '[]'::jsonb;  -- [{ref, label, source_type, source_id, title, page, ...}]
alter table queries add column if not exists input_mode text;              -- voice | text
alter table queries add column if not exists audio_path text;              -- question recording (audio bucket)
alter table queries add column if not exists audio_seconds numeric(5,1);
alter table queries add column if not exists error text;                   -- error code when status = failed
alter table queries add column if not exists model text;                   -- Groq model that wrote the answer
alter table queries add column if not exists first_token_ms int;           -- time until the first word appeared

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'queries_status_check') then
    alter table queries add constraint queries_status_check
      check (status in ('answering', 'answered', 'no_answer', 'failed', 'cancelled'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'queries_input_mode_check') then
    alter table queries add constraint queries_input_mode_check
      check (input_mode is null or input_mode in ('voice', 'text'));
  end if;
end $$;

create index if not exists queries_user_idx on queries (tenant_id, user_id, created_at desc);
create index if not exists queries_machine_idx on queries (tenant_id, machine_id, created_at desc);

-- ===================================================================== feedback
-- keep only the newest row per (query, user) before adding the unique index
delete from feedback f
using feedback g
where f.query_id = g.query_id and f.user_id = g.user_id
  and (f.created_at, f.id) < (g.created_at, g.id);

create unique index if not exists feedback_query_user_idx on feedback (query_id, user_id);

-- ===================================================================== escalations
alter table escalations add column if not exists asked_by uuid references users (id);
alter table escalations add column if not exists machine_id uuid references machines (id);
alter table escalations add column if not exists note text;                -- what the technician added ("already changed the filter")
alter table escalations add column if not exists assigned_at timestamptz;
alter table escalations add column if not exists replied_by uuid references users (id);
alter table escalations add column if not exists reply_local jsonb;        -- reply translated for the asker (cache)
alter table escalations add column if not exists closed_at timestamptz;
alter table escalations add column if not exists close_reason text;        -- fixed_by_technician | not_needed

-- status: open | answered | closed   (replace whatever check 0001 created)
do $$
declare c record;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.escalations'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%status%'
  loop
    execute format('alter table escalations drop constraint %I', c.conname);
  end loop;
  alter table escalations add constraint escalations_status_check
    check (status in ('open', 'answered', 'closed'));
end $$;

-- one escalation per question (keep the newest if there are duplicates)
delete from escalations e
using escalations d
where e.query_id = d.query_id and (e.created_at, e.id) < (d.created_at, d.id);

create unique index if not exists escalations_query_idx on escalations (query_id);
create index if not exists escalations_queue_idx on escalations (tenant_id, status, created_at);
create index if not exists escalations_assignee_idx on escalations (tenant_id, assigned_to, status);

-- ===================================================================== expert reply = Capture record
alter table repair_records add column if not exists escalation_id uuid references escalations (id) on delete set null;
create index if not exists repair_records_escalation_idx on repair_records (escalation_id) where escalation_id is not null;

create or replace function kaarigar_escalation_answered() returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.escalation_id is not null
     and new.status in ('pending', 'approved')
     and coalesce(old.status, '') not in ('pending', 'approved') then
    update escalations
       set status = 'answered',
           new_record_id = new.id,
           replied_by = new.author_id,
           answered_at = coalesce(answered_at, now()),
           reply_local = null
     where id = new.escalation_id
       and tenant_id = new.tenant_id
       and status <> 'closed';
  end if;
  return new;
end;
$$;

drop trigger if exists repair_records_escalation_answered on repair_records;
create trigger repair_records_escalation_answered
  after update of status on repair_records
  for each row execute function kaarigar_escalation_answered();

-- ===================================================================== realtime
-- The frontend only uses these events as a "something changed, refetch" signal.
-- Supabase Realtime applies RLS, so people only get events for their own plant.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'escalations') then
      alter publication supabase_realtime add table escalations;
    end if;
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'repair_records') then
      alter publication supabase_realtime add table repair_records;
    end if;
  end if;
end $$;
