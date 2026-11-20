-- Kaarigar AI — Phase 4 (manager screens W3–W8)
-- Additive and safe to run twice. Run in the Supabase SQL editor after 0004_phase3.sql.
--
-- What it adds
--   users.deactivated_at            People (W8): deactivate instead of delete (keeps their repair records)
--   machines.archived_at            Machines (W7): retire a machine without losing its history
--   machines.sticker_printed_at     Machines (W7): which QR stickers still need printing
--   repair_records.archived_at      Knowledge base (W6): take an outdated fix out of Kaarigar's answers
--   admin_audit                     who added people, reset PINs, deactivated, archived (never stores a PIN)
--   indexes for Analytics (W3)

alter table users add column if not exists deactivated_at timestamptz;
alter table users add column if not exists created_by uuid references users (id);

alter table machines add column if not exists archived_at timestamptz;
alter table machines add column if not exists sticker_printed_at timestamptz;

alter table repair_records add column if not exists archived_at timestamptz;
alter table repair_records add column if not exists archived_by uuid references users (id);

create table if not exists admin_audit (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants (id),
  actor_id    uuid references users (id),
  action      text not null,          -- person_added | pin_reset | password_reset | person_updated | person_deactivated | person_reactivated
                                      -- machine_added | machine_updated | machine_archived | machine_restored | qr_renewed
                                      -- stickers_printed | record_archived | record_restored
  target_type text not null,          -- user | machine | repair_record
  target_id   uuid,
  detail      jsonb not null default '{}'::jsonb,   -- what changed; never a PIN or password
  created_at  timestamptz not null default now()
);
create index if not exists admin_audit_tenant_idx on admin_audit (tenant_id, created_at desc);

alter table admin_audit enable row level security;
do $$
begin
  if not exists (select 1 from pg_policies where tablename = 'admin_audit' and policyname = 'same_tenant_read') then
    create policy same_tenant_read on admin_audit for select using (tenant_id = public.current_tenant_id());
  end if;
end $$;

-- Analytics (W3): everything is filtered by plant and date range
create index if not exists queries_tenant_created_idx on queries (tenant_id, created_at desc);
create index if not exists feedback_tenant_created_idx on feedback (tenant_id, created_at desc);
create index if not exists repair_records_tenant_status_idx on repair_records (tenant_id, status, created_at desc);
create index if not exists escalations_tenant_created_idx on escalations (tenant_id, created_at desc);
create index if not exists queries_citations_gin_idx on queries using gin (citations jsonb_path_ops);
create index if not exists machines_active_idx on machines (tenant_id, code) where archived_at is null;
