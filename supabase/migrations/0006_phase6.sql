-- Kaarigar AI — Phase 6 (provider fallbacks + answer cache)
-- Run after 0005_phase4.sql.

-- Grounded answers are cached so the same question on the same machine does not
-- call an LLM again. Only answers with at least one valid citation are stored.
create table if not exists answer_cache (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id) on delete cascade,
  machine_key  text not null,                 -- machine code + model, or 'any'
  question_key text not null,                 -- sha256 of the normalised English question
  chunk_key    text not null,                 -- sha256 of the ordered top chunk ids
  answer_local text not null,
  sources      jsonb not null default '[]'::jsonb,
  citations    jsonb not null default '[]'::jsonb,
  confidence   numeric,
  model        text,
  provider     text,                          -- hidden debug label, e.g. groq:openai/gpt-oss-120b
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null default (now() + interval '7 days'),
  unique (tenant_id, machine_key, question_key, chunk_key)
);

create index if not exists answer_cache_lookup_idx
  on answer_cache (tenant_id, machine_key, question_key, chunk_key, expires_at);
create index if not exists answer_cache_expiry_idx on answer_cache (expires_at);

-- The backend connects as the database owner and bypasses RLS; no public access.
alter table answer_cache enable row level security;
