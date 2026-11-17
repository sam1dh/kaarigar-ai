# Kaarigar AI

Voice-first repair copilot for Indian shop floors: technicians scan a machine QR and ask for repair help by voice; supervisors review, approve and answer escalations. Techthon 2026 — **Team Commit & Conquer**.

**Phase 2 (this repo state):** voice repair capture — experts record a repair in their own language, check the AI note, and a supervisor approves it into the searchable knowledge base.

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

## Phone testing

Browsers only allow the microphone on `https://` or `localhost`, so use the
Cloudflare named tunnel. It serves two addresses:

| Address | Serves | Start |
|---|---|---|
| `https://dev.kaarigar-ai.online` | Vite dev server on `:5173` (live reload while coding) | `npm run dev:phone` + tunnel |
| `https://app.kaarigar-ai.online` | built preview on `:4173` (PWA / demo) | `npm run phone` + tunnel |

1. Start the backend on `:8000` (`cd backend && uvicorn app.main:app --reload`).
2. Start one frontend (only one Vite server on `:5173`):
   ```bash
   cd frontend
   npm run dev:phone   # live while coding
   # or:
   npm run phone       # built app, for demos / installing the PWA
   ```
3. Start the named tunnel (needs `.tunnel-token` in the repo root — never commit it):
   ```bash
   cd frontend
   npm run tunnel
   ```

Open **https://dev.kaarigar-ai.online** on your phone while coding: saving a
file updates the phone within a second or two. Use **https://app.kaarigar-ai.online**
for the built app and *Install app* (the PWA is named **Kaarigar**).
Sign in as **SH-0412 / 482913** (technician) or **SH-0107 / 261847** (expert).

- `dev:` reloads through the tunnel via `TUNNEL_DEV=1` (HMR on `wss://…:443`).
  Plain `npm run dev` keeps normal HMR on `http://localhost:5173`.
- `app:` rebuild after code changes: rerun `npm run phone` (the preview serves
  the built `dist/`, not live source).
- If it can't connect on college Wi-Fi, add `--protocol http2` to the
  `cloudflared` command (campus networks often block the UDP the tunnel uses).

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
