"""Pydantic request/response models."""

from pydantic import BaseModel, Field


class PinLoginRequest(BaseModel):
    plant_code: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    pin: str = Field(min_length=4, max_length=8)


class ProfileOut(BaseModel):
    id: str
    name: str
    employee_id: str | None = None
    role: str
    is_admin: bool
    language: str
    tenant: dict


class PinLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    profile: ProfileOut


class LanguageUpdate(BaseModel):
    language: str = Field(min_length=2, max_length=12)


class MachineOut(BaseModel):
    id: str
    code: str
    name: str | None
    line: str | None
    model: str | None
