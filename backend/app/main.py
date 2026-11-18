"""Kaarigar AI backend — FastAPI app."""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.capture.router_capture import router as capture_router
from app.capture.router_review import router as review_router
from app.capture.runner import init_capture, shutdown_capture
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.routers import admin, auth, manager, tech

app = FastAPI(title="Kaarigar AI", version="0.1.0")

settings = get_settings()
app.state.settings = settings

logging.basicConfig(level=logging.INFO)
app.logger = logging.getLogger("kaarigar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def json_access_log(request: Request, call_next):
    """JSON logs with request_id, route, user_id, ms. Never logs tokens or PINs."""
    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        ms = int((time.perf_counter() - start) * 1000)
        app.logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "route": request.url.path,
                    "user_id": getattr(request.state, "user_id", None),
                    "ms": ms,
                    "status": 500,
                }
            )
        )
        raise
    ms = int((time.perf_counter() - start) * 1000)
    app.logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "route": request.url.path,
                "user_id": getattr(request.state, "user_id", None),
                "ms": ms,
                "status": response.status_code,
            }
        )
    )
    response.headers["X-Request-Id"] = request_id
    return response


app.include_router(auth.router)
app.include_router(tech.router)
app.include_router(manager.router)
app.include_router(admin.router)
app.include_router(capture_router)
app.include_router(review_router)


@app.on_event("startup")
def startup() -> None:
    # Phase 1: psycopg pool (lazy on first use), embed model in the background,
    # and any job queued by the previous process is dead.
    if settings.database_url:
        from app.services import embeddings, jobs

        jobs.fail_stale_jobs()
        embeddings.start_loading()

    # Phase 2: capture graph (checkpoints in the `langgraph` schema)
    if settings.database_url:
        init_capture()

    # Warm Supabase TLS/keep-alive connections and the profile cache so the first
    # PIN login does not pay for two handshakes plus a profile round-trip. This
    # runs before readiness, which is fine: startup already waits on the DB.
    from app.routers.auth import warm_connections

    warm_connections()


@app.on_event("shutdown")
def shutdown() -> None:
    # Stop background capture runs before closing their checkpoint pool.
    shutdown_capture()
    if settings.database_url:
        from app.core.db import close_pool

        close_pool()


@app.get("/health")
def health() -> dict:
    if settings.database_url:
        from app.services import embeddings

        return {"status": "ok", "models": embeddings.status()}
    return {"status": "ok"}


# /dev/search + /dev/stats: only in development
if settings.app_env == "development":
    from app.routers import dev

    app.include_router(dev.router)


install_error_handlers(app)
