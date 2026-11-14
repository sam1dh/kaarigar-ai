-- Kaarigar AI — full schema (Phase 0)
-- Run once in the Supabase SQL editor (Mumbai region project).

-- Extensions
create extension if not exists vector;
create extension if not exists pg_trgm;
create extension if not exists pgcrypto;

-- ===== Setup =====
create table tenants (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  slug        text not null unique,           -- e.g. 'shree' (used as plant code)
  city        text,
  created_at  timestamptz not null default now()
);

create table users (
  id          uuid primary key references auth.users(id) on delete cascade,
  tenant_id   uuid not null references tenants(id),
  name        text not null,
  employee_id text,
  role        text not null check (role in ('technician','expert','supervisor')),
  is_admin    boolean not null default false,
  language    text not null default 'hi-IN',
  created_at  timestamptz not null default now(),
  unique (tenant_id, employee_id)
);

create table machine_models (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  oem         text,
  model       text not null,
  type        text,                             -- 'hydraulic press', 'cnc lathe', ...
  created_at  timestamptz not null default now()
);

create table machines (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  model_id    uuid references machine_models(id),
  code        text not null,                    -- 'HP-07'
  name        text,                             -- 'Hydraulic press'
  line        text,                             -- 'Line 2'
  qr_token    text not null unique default encode(gen_random_bytes(12), 'hex'),
  created_at  timestamptz not null default now(),
  unique (tenant_id, code)
);

create table glossary (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  term        text not null,                    -- 'thak-thak'
  meaning     text,                             -- 'knocking sound'
  keep_in_english boolean not null default false,
  unique (tenant_id, term)
);

-- ===== Sources =====
create table documents (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id),
  model_id      uuid references machine_models(id),
  title         text not null,
  type          text not null check (type in ('manual','sop','safety')),
  file_path     text not null,
  status        text not null default 'uploaded' check (status in ('uploaded','parsing','ready','failed')),
  pages         int,
  quality_notes text,
  created_by    uuid references users(id),
  created_at    timestamptz not null default now()
);

create table log_imports (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants(id),
  file_path      text not null,
  column_mapping jsonb,
  status         text not null default 'uploaded' check (status in ('uploaded','mapping','importing','done','failed')),
  rows_ok        int not null default 0,
  rows_skipped   int not null default 0,
  created_by     uuid references users(id),
  created_at     timestamptz not null default now()
);

create table maintenance_logs (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  machine_id   uuid references machines(id),
  import_id    uuid references log_imports(id),
  date         date,
  fault        text,
  action       text,
  downtime_min int,
  technician   text,
  raw          jsonb,
  created_at   timestamptz not null default now()
);

-- ===== Knowledge =====
create table symptoms (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), name text not null, aliases text[] not null default '{}', unique (tenant_id, name));
create table causes   (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), name text not null, aliases text[] not null default '{}', unique (tenant_id, name));
create table fixes    (id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenants(id), name text not null, aliases text[] not null default '{}', unique (tenant_id, name));

create table repair_records (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id),
  machine_id    uuid not null references machines(id),
  author_id     uuid not null references users(id),
  audio_path    text,
  transcript_en text,
  symptom_id    uuid references symptoms(id),
  cause_id      uuid references causes(id),
  fix_id        uuid references fixes(id),
  safety_note   text,
  fields        jsonb,
  ai_check      jsonb,
  status        text not null default 'draft' check (status in ('draft','expert_review','pending','approved','rejected')),
  reject_reason text,
  reviewed_by   uuid references users(id),
  reviewed_at   timestamptz,
  source        text not null default 'capture' check (source in ('capture','escalation','seed')),
  created_at    timestamptz not null default now()
);

-- ===== Search (one table for manuals, records, logs) =====
create table chunks (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  source_type text not null check (source_type in ('manual','record','log')),
  source_id   uuid not null,
  machine_id  uuid references machines(id),
  model_id    uuid references machine_models(id),
  section     text,
  text        text not null,
  embedding   vector(384),
  tsv         tsvector generated always as (to_tsvector('english', text)) stored,
  created_at  timestamptz not null default now()
);
create index chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index chunks_tsv_idx       on chunks using gin (tsv);
create index chunks_trgm_idx      on chunks using gin (text gin_trgm_ops);
create index chunks_scope_idx     on chunks (tenant_id, machine_id, model_id);

-- ===== Activity =====
create table queries (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants(id),
  user_id           uuid not null references users(id),
  machine_id        uuid references machines(id),
  question_original text,
  question_en       text,
  language          text,
  answer            text,
  confidence        real,
  citations         jsonb,
  escalated         boolean not null default false,
  latency_ms        int,
  created_at        timestamptz not null default now()
);

create table feedback (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id),
  query_id   uuid not null references queries(id) on delete cascade,
  user_id    uuid not null references users(id),
  outcome    text not null check (outcome in ('fixed','not_fixed','call_supervisor')),
  created_at timestamptz not null default now()
);

create table escalations (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id),
  query_id         uuid not null references queries(id),
  assigned_to      uuid references users(id),
  status           text not null default 'open' check (status in ('open','answered')),
  reply_text       text,
  reply_audio_path text,
  new_record_id    uuid references repair_records(id),
  created_at       timestamptz not null default now(),
  answered_at      timestamptz
);

create table jobs (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id),
  type       text not null,                     -- 'ingest_pdf' | 'import_logs' | 'batch_stt'
  ref_id     uuid,
  status     text not null default 'queued' check (status in ('queued','running','done','failed')),
  progress   int not null default 0,
  error      text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ===== Row Level Security =====
-- Helper: the logged-in user's plant
create or replace function public.current_tenant_id()
returns uuid language sql stable security definer set search_path = public as $$
  select tenant_id from public.users where id = auth.uid()
$$;

alter table tenants enable row level security;
create policy tenant_self_read on tenants for select using (id = public.current_tenant_id());

do $$
declare t text;
begin
  foreach t in array array[
    'users','machine_models','machines','glossary','documents','log_imports','maintenance_logs',
    'symptoms','causes','fixes','repair_records','chunks','queries','feedback','escalations','jobs'
  ] loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy same_tenant_read on %I for select using (tenant_id = public.current_tenant_id())', t);
  end loop;
end $$;
-- Writes happen through the backend with the service-role key (bypasses RLS).

-- ===== Storage buckets (private) =====
insert into storage.buckets (id, name, public) values
  ('audio','audio',false), ('tts','tts',false), ('documents','documents',false), ('imports','imports',false)
on conflict (id) do nothing;

-- ===== Realtime (supervisor escalation alerts, used in Phase 4) =====
alter publication supabase_realtime add table escalations;
