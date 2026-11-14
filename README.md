# Kaarigar AI

Voice-first repair copilot for Indian shop floors: technicians scan a machine QR and ask for repair help by voice; supervisors review, approve and answer escalations. Techthon 2026 — **Team Commit & Conquer**.

**Phase 0 (this repo state):** foundations only — Supabase schema, PIN/email login, roles, routing, empty screens. No AI, no voice, no search yet.

## Stack

- **Frontend:** Vite + React 18 + TypeScript, Tailwind CSS, shadcn/ui, React Router, TanStack Query, Zustand, react-i18next, `vite-plugin-pwa`, `@supabase/supabase-js` (in `frontend/`)
- **Backend:** Python 3.11, FastAPI, Uvicorn, Pydantic v2 + pydantic-settings, supabase-py, PyJWT[crypto] (in `backend/`)
- **Database / Auth / Files / Realtime:** Supabase (cloud, Mumbai region) — Postgres + pgvector + pg_trgm
- **Phone testing:** Cloudflare Tunnel (`cloudflared`)
- **Lint/format:** ruff (Python), ESLint + Prettier (TS)

## Prerequisites

- Node 20+
- Python 3.11+
- Docker (optional — you can also run the backend directly)
- A Supabase project (Mumbai region)
- `cloudflared` (for testing the PWA on a real phone)

## Setup

1. Copy the env files and fill in your Supabase keys:

   ```bash
   cp .env.example .env
   cp frontend/.env.example frontend/.env   # VITE_* variables
   ```

   (`frontend/.env.example` — create it from the VITE_* block in `.env.example`.)

2. Create the schema: run `supabase/migrations/0001_init.sql` in the Supabase SQL editor
   (or: `cd backend && .venv/bin/python scripts/run_migrations.py` with `DATABASE_URL` set).

3. Seed the demo plant:

   ```bash
   cd /path/to/kaarigar-ai
   python backend/scripts/seed.py
   ```

   Idempotent — safe to run twice. Prints every machine's `qr_token` and the demo logins.

## Run

```bash
# backend (either way)
docker compose up
# or:
cd backend && uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev
```

Dev proxy: `/api` on :5173 forwards to the backend on :8000.

## Test on a real phone

```bash
cloudflared tunnel --url http://localhost:5173
```

Open the printed `*.trycloudflare.com` URL on your phone → sign in as **SH-0412 / 482913**.
In Chrome you can also *Install app* — the PWA is named **Kaarigar**.

## Demo logins (after seeding)

| Who | Login | Role |
|---|---|---|
| Amit Kale | Phone: `SH-0412` + PIN `482913` | technician |
| Priya Shinde | Phone: `SH-0233` + PIN `735104` | technician |
| Ramesh Patil | Phone: `SH-0107` + PIN `261847` | expert |
| Karthik Raman | Phone: `SH-0518` + PIN `590372` | technician (Tamil) |
| Suresh Kulkarni | Web: `suresh@shreehydraulics.in` + `SEED_ADMIN_PASSWORD` | supervisor · admin |

Technician/expert auth emails are hidden: `<employee_id>@<plant_code>.employees.kaarigar.app`.

## Layout

```
supabase/migrations/0001_init.sql   # full schema (run once)
docs/schema.dbml                    # ER diagram for dbdiagram.io (keep in sync)
docs/designs/*.pdf                  # approved designs (source of truth for UI)
backend/  FastAPI app, seed script, tests
frontend/ Vite React PWA
```
