"""/admin/machines — W7 Machines + QR stickers. Plant admins only.

A machine's QR sticker opens PUBLIC_APP_URL/m/<qr_token> (Phase 3's QrRedirect).
"New QR" makes the old sticker stop working (lost or damaged stickers).
Machines are archived, never deleted, so their history and repair records stay.
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.capture.errors import api_error

from .adapters import ManageUser
from .deps import admin, get_repo
from .settings import get_manage_settings
from .views import machine_view

router = APIRouter(prefix="/admin", tags=["machines"])

CODE = re.compile(r"^[A-Z]{1,6}-?\d{1,4}[A-Z]?$")


def normalize_code(raw: str) -> str:
    s = re.sub(r"\s+", "-", raw.strip().upper())
    return re.sub(r"-+", "-", s).strip("-")


def code_key(code: str) -> str:
    """Same rule as Phase 1's breakdown-log import: HP-07, HP 07, hp7 are the same machine."""
    s = re.sub(r"[^A-Z0-9]", "", code.upper())
    m = re.match(r"^([A-Z]+)0*(\d+)([A-Z]?)$", s)
    return f"{m.group(1)}{int(m.group(2))}{m.group(3)}" if m else s


class NewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=60)
    type: str | None = Field(default=None, max_length=60)
    oem: str | None = Field(default=None, max_length=80)


class NewMachine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=16)
    name: str | None = Field(default=None, max_length=80)
    line: str | None = Field(default=None, max_length=40)
    model_id: str | None = None
    new_model: NewModel | None = None


class MachinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None, min_length=2, max_length=16)
    name: str | None = Field(default=None, max_length=80)
    line: str | None = Field(default=None, max_length=40)
    model_id: str | None = None


class MachineIds(BaseModel):
    machine_ids: list[str] = Field(min_length=1)


def _uuid(v: str, what: str = "id") -> str:
    try:
        return str(uuid.UUID(v))
    except (ValueError, TypeError):
        raise api_error(422, "invalid_id", f"Not a valid {what}.")


def _clean(v: str | None) -> str | None:
    v = " ".join((v or "").split())
    return v or None


def _view(row: dict) -> dict:
    return machine_view(row, public_url=get_manage_settings().PUBLIC_APP_URL)


def _check_code(repo, tenant_id: str, raw: str, exclude_id: str | None = None) -> str:
    code = normalize_code(raw)
    if not CODE.match(code):
        raise api_error(422, "bad_code", "Machine code: letters then a number, like HP-07 or CNC-03.")
    key = code_key(code)
    for m in repo.machine_codes(tenant_id):
        if str(m["id"]) != (exclude_id or "") and code_key(m["code"]) == key:
            raise api_error(409, "code_taken", f"{m['code']} already exists (same machine code).")
    return code


def _resolve_model(repo, tenant_id: str, model_id: str | None, new_model: NewModel | None) -> str | None:
    if model_id and new_model:
        raise api_error(422, "one_model", "Pick an existing model or add a new one, not both.")
    if model_id:
        if not repo.model_in_tenant(tenant_id, _uuid(model_id, "model id")):
            raise api_error(404, "model_not_found", "Machine model not found.")
        return _uuid(model_id)
    if new_model:
        name = " ".join(new_model.model.split())
        existing = repo.find_model(tenant_id, name)
        if existing:
            return str(existing["id"])
        return str(repo.insert_model(tenant_id, name, _clean(new_model.type), _clean(new_model.oem))["id"])
    return None


def _load(repo, user: ManageUser, machine_id: str) -> dict:
    row = repo.get_machine(user.tenant_id, _uuid(machine_id, "machine id"))
    if not row:
        raise api_error(404, "not_found", "Machine not found.")
    return row


@router.get("/machines")
def list_machines(include_archived: bool = False, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    rows = repo.list_machines(user.tenant_id, include_archived)
    items = [_view(r) for r in rows]
    active = [i for i in items if not i["archived"]]
    return {"items": items, "counts": {"active": len(active), "archived": len(items) - len(active),
                                       "stickers_missing": sum(1 for i in active if not i["sticker_printed_at"])}}


@router.post("/machines", status_code=201)
def add_machine(body: NewMachine, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    code = _check_code(repo, user.tenant_id, body.code)
    model_id = _resolve_model(repo, user.tenant_id, body.model_id, body.new_model)
    mid = repo.insert_machine(user.tenant_id, code, _clean(body.name), _clean(body.line), model_id)
    repo.audit(user.tenant_id, user.id, "machine_added", "machine", mid, {"code": code})
    return _view(repo.get_machine(user.tenant_id, mid))


@router.patch("/machines/{machine_id}")
def update_machine(machine_id: str, body: MachinePatch, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    row = _load(repo, user, machine_id)
    changes: dict = {}
    sent = body.model_fields_set
    if body.code is not None and normalize_code(body.code) != row["code"]:
        changes["code"] = _check_code(repo, user.tenant_id, body.code, exclude_id=str(row["id"]))
    if "name" in sent:
        changes["name"] = _clean(body.name)
    if "line" in sent:
        changes["line"] = _clean(body.line)
    if "model_id" in sent:
        changes["model_id"] = _resolve_model(repo, user.tenant_id, body.model_id, None)
    if changes:
        repo.update_machine(user.tenant_id, str(row["id"]), **changes)
        repo.audit(user.tenant_id, user.id, "machine_updated", "machine", str(row["id"]),
                   {k: v for k, v in changes.items()})
    return _view(repo.get_machine(user.tenant_id, str(row["id"])))


@router.post("/machines/{machine_id}/archive")
def archive_machine(machine_id: str, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    row = _load(repo, user, machine_id)
    if row.get("archived_at"):
        raise api_error(409, "already_archived", "Already archived.")
    repo.set_machine_archived(user.tenant_id, str(row["id"]), True)
    repo.audit(user.tenant_id, user.id, "machine_archived", "machine", str(row["id"]), {"code": row["code"]})
    return _view(repo.get_machine(user.tenant_id, str(row["id"])))


@router.post("/machines/{machine_id}/restore")
def restore_machine(machine_id: str, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    row = _load(repo, user, machine_id)
    if not row.get("archived_at"):
        raise api_error(409, "not_archived", "This machine is not archived.")
    repo.set_machine_archived(user.tenant_id, str(row["id"]), False)
    repo.audit(user.tenant_id, user.id, "machine_restored", "machine", str(row["id"]), {"code": row["code"]})
    return _view(repo.get_machine(user.tenant_id, str(row["id"])))


@router.post("/machines/{machine_id}/new-qr")
def new_qr(machine_id: str, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    row = _load(repo, user, machine_id)
    repo.renew_qr(user.tenant_id, str(row["id"]))
    repo.audit(user.tenant_id, user.id, "qr_renewed", "machine", str(row["id"]), {"code": row["code"]})
    return _view(repo.get_machine(user.tenant_id, str(row["id"])))


def _ids(repo, user: ManageUser, body: MachineIds) -> list[dict]:
    limit = get_manage_settings().STICKERS_MAX
    ids = list(dict.fromkeys(_uuid(i, "machine id") for i in body.machine_ids))
    if len(ids) > limit:
        raise api_error(422, "too_many", f"Print at most {limit} stickers at a time.")
    rows = repo.machines_by_ids(user.tenant_id, ids)
    if len(rows) != len(ids):
        raise api_error(404, "not_found", "One of these machines was not found.")
    return rows


@router.post("/machines/stickers")
def stickers(body: MachineIds, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    """QR codes as inline SVG (drawn by segno), ready for the print page."""
    import segno

    base = get_manage_settings().PUBLIC_APP_URL.rstrip("/")
    out = []
    for r in _ids(repo, user, body):
        url = f"{base}/m/{r['qr_token']}"
        svg = segno.make(url, error="m").svg_inline(scale=4, border=0, dark="#1C2626", omitsize=True,
                                                    title=f"QR code for {r['code']}")   # viewBox: scales when printed
        out.append({"id": str(r["id"]), "code": r["code"], "name": r.get("name"), "line": r.get("line"),
                    "model": r.get("model"), "url": url, "svg": svg})
    return {"items": out}


@router.post("/machines/stickers/printed")
def stickers_printed(body: MachineIds, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    rows = _ids(repo, user, body)
    n = repo.mark_printed(user.tenant_id, [str(r["id"]) for r in rows])
    repo.audit(user.tenant_id, user.id, "stickers_printed", "machine", None, {"codes": [r["code"] for r in rows]})
    return {"marked": n}


@router.post("/machine-models", status_code=201)
def add_model(body: NewModel, user: ManageUser = Depends(admin), repo=Depends(get_repo)):
    name = " ".join(body.model.split())
    if repo.find_model(user.tenant_id, name):
        raise api_error(409, "model_exists", f"Model {name} already exists.")
    row = repo.insert_model(user.tenant_id, name, _clean(body.type), _clean(body.oem))
    return {"id": str(row["id"]), "model": row["model"], "type": row.get("type"), "oem": row.get("oem"), "machines": []}
