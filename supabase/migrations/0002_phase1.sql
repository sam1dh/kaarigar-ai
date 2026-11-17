-- Kaarigar AI — Phase 1: knowledge in (additive only; never edit 0001_init.sql)

-- ===== chunks: page numbers for manual citations, order inside a source, extra info =====
alter table chunks add column if not exists page int;
alter table chunks add column if not exists chunk_index int not null default 0;
alter table chunks add column if not exists meta jsonb not null default '{}'::jsonb;
create index if not exists chunks_source_idx on chunks (source_type, source_id);

-- ===== documents: error message + duplicate detection =====
alter table documents add column if not exists error text;
alter table documents add column if not exists file_hash text;

-- ===== log imports: what was detected in the file, duplicate detection =====
alter table log_imports add column if not exists file_name text;
alter table log_imports add column if not exists file_hash text;
alter table log_imports add column if not exists detected jsonb;  -- {header_row, columns, sample_rows, total_rows, mapping_source, skipped:[{row, reason}]}
create index if not exists log_imports_hash_idx on log_imports (tenant_id, file_hash);

-- ===== graph retriever helpers =====
create index if not exists symptoms_name_trgm_idx on symptoms using gin (name gin_trgm_ops);
create index if not exists repair_records_symptom_idx on repair_records (tenant_id, symptom_id) where status = 'approved';
create index if not exists repair_records_seed_key_idx on repair_records ((fields->>'seed_key'));
create index if not exists maintenance_logs_machine_idx on maintenance_logs (tenant_id, machine_id, date desc);
