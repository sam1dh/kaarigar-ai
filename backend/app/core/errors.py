"""Standard error shape: {"error": {"code": "...", "message": "..."}}."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    """API error carrying a stable code.

    Subclasses HTTPException so routers mounted in a bare FastAPI app (tests,
    isolated packs) still return a useful body ({"detail": {"error": ...}})
    instead of raising. The app installs a handler that emits the flat
    {"error": {...}} envelope used by the frontend.
    """

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(status_code=status, detail={"error": {"code": code, "message": message}})


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Same envelope as every other error — no FastAPI internals leaked.
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p not in ("body", "__root__"))
        msg = f"Invalid request: {loc} {first.get('msg', '')}".strip()
        return JSONResponse(status_code=422, content=error_body("validation_error", msg))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internals; log the exception server-side only.
        app.logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong. Please try again."),
        )
