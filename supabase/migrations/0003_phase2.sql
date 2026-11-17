-- Kaarigar AI — Phase 2: Capture
-- Additive only. Run in the Supabase SQL editor after 0001 and 0002.

-- 1) Capture details on repair_records
alter table repair_records add column if not exists language text;                 -- Sarvam code the expert spoke / reads in
alter table repair_records add column if not exists audio_seconds numeric(6,1);
alter table repair_records add column if not exists stage text;                    -- queued | transcribing | extracting | checking | translating | ready | failed
alter table repair_records add column if not exists error text;                    -- friendly message when stage = failed
alter table repair_records add column if not exists fields_local jsonb;            -- the fields translated into `language` for the expert's check screen
alter table repair_records add column if not exists submitted_at timestamptz;      -- when the expert sent it to the supervisor
alter table repair_records add column if not exists edited_by_expert boolean not null default false;
alter table repair_records add column if not exists edited_by_reviewer boolean not null default false;

alter table repair_records drop constraint if exists repair_records_stage_check;
alter table repair_records add constraint repair_records_stage_check
  check (stage is null or stage in ('queued','transcribing','extracting','checking','translating','ready','failed'));

create index if not exists repair_records_queue_idx  on repair_records (tenant_id, status, submitted_at);
create index if not exists repair_records_author_idx on repair_records (tenant_id, author_id, created_at desc);

-- 2) LangGraph checkpoints live in their own schema.
--    The Supabase Data API only exposes `public`, so anon/authenticated keys can never read graph state.
--    The backend creates the tables inside it on startup (PostgresSaver.setup()).
create schema if not exists langgraph;
revoke all on schema langgraph from anon, authenticated;
