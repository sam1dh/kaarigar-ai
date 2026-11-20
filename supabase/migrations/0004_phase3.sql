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
