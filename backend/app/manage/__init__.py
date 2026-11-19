"""Phase 4 — the manager side: People (W8), Machines + QR stickers (W7), Knowledge base (W6),
Analytics (W3), and lists for Documents (W4) and Breakdown logs (W5).

Package layout
- adapters.py        the ONLY file that imports earlier phases (user, db, Phase 1 knowledge chunks)
- settings.py        Phase 4 settings (same .env)
- auth_admin.py      Supabase Auth admin REST calls: create login, set PIN/password, block/unblock
- secrets_gen.py     6-digit PINs (no 111111 / 123456 patterns) and temporary passwords
- repo.py            all SQL for this phase (tenant-scoped)
- views.py           rows -> API responses
- deps.py            role checks + overridable dependencies (tests swap repo/auth)
- router_people.py   /admin/people*
- router_machines.py /admin/machines*, POST /admin/machine-models
- router_knowledge.py /manager/knowledge*
- router_analytics.py /manager/analytics
- router_logs.py     GET /admin/log-imports (history), GET /admin/maintenance-logs
- routers.py         manage_routers: the list main.py includes
"""
