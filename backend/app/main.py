"""Kaarigar AI backend — FastAPI app."""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


install_error_handlers(app)
