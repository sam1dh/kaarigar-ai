"""Lists for W5 Breakdown logs. Uploading and importing stay in Phase 1's endpoints:
POST /admin/log-imports, POST /admin/log-imports/{id}/confirm, GET /admin/log-imports/{id}, GET /admin/jobs/{id}."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .adapters import ManageUser
from .deps import admin, get_repo
from .views import iso

router = APIRouter(prefix="/admin", tags=["breakdown logs"])


@router.get("/log-imports")
def import_history(limit: int = Query(20, ge=1, le=100), user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    return {"items": [{"id": str(r["id"]), "file_name": r.get("file_name"), "status": r["status"],
                       "rows_ok": int(r.get("rows_ok") or 0), "rows_skipped": int(r.get("rows_skipped") or 0),
                       "created_at": iso(r["created_at"]), "created_by": r.get("created_by_name")}
                      for r in repo.list_log_imports(user.tenant_id, limit)]}


@router.get("/maintenance-logs")
def maintenance_logs(machine: str | None = Query(None, max_length=20), limit: int = Query(50, ge=1, le=200),
                     user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    machine = machine.strip() if machine and machine.strip() else None
    return {"items": [{"id": str(r["id"]), "date": iso(r.get("date")), "machine": r.get("machine_code"),
                       "fault": r.get("fault"), "action": r.get("action"), "downtime_min": r.get("downtime_min"),
                       "technician": r.get("technician"), "file_name": r.get("file_name")}
                      for r in repo.list_maintenance_logs(user.tenant_id, machine, limit)]}
