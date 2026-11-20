"""Technician endpoints: ping, machine list, machine lookup by QR token."""

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_role
from app.core.supabase import admin_client
from app.schemas import MachineOut

router = APIRouter(prefix="/tech", tags=["tech"])

TECH_ROLES = ("technician", "expert", "supervisor")


@router.get("/ping")
def ping(_: CurrentUser = Depends(require_role(*TECH_ROLES))) -> dict:
    return {"ok": True, "area": "tech"}


def _machine_out(d: dict) -> MachineOut:
    model = d.get("machine_models") or {}
    model_name = model.get("model") if isinstance(model, dict) else None
    return MachineOut(
        id=str(d["id"]),
        code=d["code"],
        name=d.get("name"),
        line=d.get("line"),
        model=model_name,
    )


@router.get("/machines", response_model=list[MachineOut])
def machines(user: CurrentUser = Depends(require_role(*TECH_ROLES))) -> list[MachineOut]:
    rows = (
        admin_client()
        .table("machines")
        .select("id, code, name, line, machine_models(model)")
        .eq("tenant_id", user.tenant_id)
        .is_("archived_at", "null")
        .order("code")
        .execute()
    )
    return [_machine_out(d) for d in rows.data or []]


@router.get("/machines/by-qr/{token}", response_model=MachineOut)
def machine_by_qr(token: str, user: CurrentUser = Depends(require_role(*TECH_ROLES))) -> MachineOut:
    rows = (
        admin_client()
        .table("machines")
        .select("id, code, name, line, machine_models(model)")
        .eq("tenant_id", user.tenant_id)  # same plant only
        .is_("archived_at", "null")  # a retired machine's old sticker stops opening it
        .eq("qr_token", token)
        .limit(1)
        .execute()
    )
    data = rows.data or []
    if not data:
        from app.core.errors import ApiError

        raise ApiError(
            404, "machine_not_found", "This QR sticker doesn't match a machine in your plant."
        )
    return _machine_out(data[0])
