"""FastAPI application factory for the local website."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.exceptions import HTTPException as StarletteHTTPException

from ffcs_studio.config import Settings
from ffcs_studio.version import VTOP_SCHEMA_VERSION, __version__
from ffcs_studio.web.security import LocalSecurityMiddleware

WEB_ROOT = Path(__file__).resolve().parent
TEMPLATES = Environment(
    loader=FileSystemLoader(WEB_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
    enable_async=False,
)


def _error_code(status_code: int) -> str:
    return {
        404: "not_found",
        405: "method_not_allowed",
    }.get(status_code, "http_error")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated app instance suitable for production or tests."""

    runtime = settings or Settings.from_env()
    app = FastAPI(
        title="FFCS Studio",
        version=__version__,
        debug=False,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = runtime
    app.add_middleware(LocalSecurityMiddleware, settings=runtime)
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": _error_code(exc.status_code), "message": detail}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "Request validation failed"}},
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing(_request: Request) -> HTMLResponse:
        template = TEMPLATES.get_template("index.html")
        html = template.render(
            app_version=__version__,
            schema_version=VTOP_SCHEMA_VERSION,
        )
        return HTMLResponse(html)

    @app.get("/health", tags=["runtime"])
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ready",
                "application": "ffcs-studio",
                "version": __version__,
                "schema_version": VTOP_SCHEMA_VERSION,
            },
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
