"""THE ONLY FILE IN app/manage THAT TOUCHES EARLIER PHASES.

Reuses Phase 2's adapters (current user, db connection), so the ADAPT work done in
app/capture/adapters.py covers this too. New ADAPT points:
  - rebuild_record_chunks(): Phase 1's knowledge service (puts a restored record back into search)
"""
from __future__ import annotations

from app.capture.adapters import (  # noqa: F401  re-exported on purpose
    CaptureUser as ManageUser,
    capture_user as manage_user,
    db_conn,
)


def forget_profile(user_id: str) -> None:
    """Phase 0: drop the auth profile cache so deactivation/role changes apply at once."""
    from app.core.auth import forget_profile as forget

    forget(user_id)


def rebuild_record_chunks(record_id: str) -> None:
    """Phase 1: delete + insert the record's search chunk (only approved records get one)."""
    from app.services.knowledge import rebuild_record_chunks as rebuild  # ADAPT if Phase 1 named it differently

    rebuild(record_id)
