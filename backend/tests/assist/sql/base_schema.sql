-- Test-only stand-in for 0001-0003 (tables Phase 3 touches), built from docs/schema.dbml.
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
