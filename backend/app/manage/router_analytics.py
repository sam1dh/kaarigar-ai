"""/manager/analytics — W3 Analytics (with the team numbers that used to be a separate "Team" screen)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends

from .adapters import ManageUser
from .deps import get_repo, supervisor
from .views import analytics_view

router = APIRouter(prefix="/manager", tags=["analytics"])


@router.get("/analytics")
def analytics(days: Literal["7", "30", "90"] = "30", user: ManageUser = Depends(supervisor), repo=Depends(get_repo)):
    d = int(days)
    return analytics_view(repo.analytics(user.tenant_id, d), d)
