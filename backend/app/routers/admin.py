"""Admin endpoints (supervisors with is_admin = true)."""

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
def ping(_: CurrentUser = Depends(require_admin)) -> dict:
    return {"ok": True, "area": "admin"}
