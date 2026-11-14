"""Manager endpoints (supervisors)."""

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_role

router = APIRouter(prefix="/manager", tags=["manager"])


@router.get("/ping")
def ping(_: CurrentUser = Depends(require_role("supervisor"))) -> dict:
    return {"ok": True, "area": "manager"}
