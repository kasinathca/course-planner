"""FastAPI application factory for the local website."""

from __future__ import annotations

import json
import secrets
import sqlite3
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.exceptions import HTTPException as StarletteHTTPException

from ffcs_studio.config import Settings
from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.database import Database, DatabaseError
from ffcs_studio.persistence.repositories import Repository
from ffcs_studio.services.calendar_service import (
    CalendarService,
    CalendarServiceError,
    CalendarTokenNotFound,
    InvalidCalendar,
)
from ffcs_studio.services.catalog_service import CatalogService
from ffcs_studio.services.import_service import (
    ImportService,
    ImportServiceError,
    StalePreview,
    TemporaryRecordNotFound,
    UnsafeFilename,
    UnsupportedUpload,
)
from ffcs_studio.services.solver_jobs import (
    SolverJobConflict,
    SolverJobError,
    SolverJobManager,
    SolverJobNotFound,
)
from ffcs_studio.services.solver_service import SolverService
from ffcs_studio.version import VTOP_SCHEMA_VERSION, __version__
from ffcs_studio.web.routes.calendars import router as calendars_router
from ffcs_studio.web.routes.courses import router as courses_router
from ffcs_studio.web.routes.imports import router as imports_router
from ffcs_studio.web.routes.solver import router as solver_router
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
    database = Database(runtime.database_path, runtime.sqlite_busy_timeout_ms)
    database_schema_version = database.initialize()
    repository = Repository(database)
    calendar_repository = CalendarRepository(database)
    schema_text = (
        resources.files("ffcs_studio.resources.schemas")
        .joinpath("slot-calendar.schema.json")
        .read_text(encoding="utf-8")
    )
    calendar_service = CalendarService(calendar_repository, json.loads(schema_text))
    import_service = ImportService(
        database,
        repository,
        preview_ttl_seconds=runtime.preview_ttl_seconds,
    )
    csrf_token = secrets.token_urlsafe(32)
    app = FastAPI(
        title="FFCS Studio",
        version=__version__,
        debug=False,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = runtime
    app.state.database = database
    app.state.repository = repository
    app.state.calendar_repository = calendar_repository
    app.state.calendar_service = calendar_service
    app.state.import_service = import_service
    app.state.catalog_service = CatalogService(repository)
    app.state.solver_service = SolverService(repository, calendar_repository)
    app.state.solver_jobs = SolverJobManager(
        max_workers=runtime.solver_max_workers,
        cancel_grace_seconds=runtime.solver_cancel_grace_seconds,
    )
    app.state.csrf_token = csrf_token
    app.state.database_schema_version = database_schema_version
    app.add_middleware(LocalSecurityMiddleware, settings=runtime, csrf_token=csrf_token)
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")
    app.include_router(imports_router)
    app.include_router(courses_router)
    app.include_router(calendars_router)
    app.include_router(solver_router)
    app.add_event_handler("shutdown", app.state.solver_jobs.shutdown)

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

    @app.exception_handler(ImportServiceError)
    async def import_error(_request: Request, exc: ImportServiceError) -> JSONResponse:
        if isinstance(exc, UnsupportedUpload):
            status_code = 415
        elif isinstance(exc, UnsafeFilename):
            status_code = 400
        elif isinstance(exc, TemporaryRecordNotFound):
            status_code = 410
        elif isinstance(exc, StalePreview):
            status_code = 409
        else:
            status_code = 400
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(CalendarServiceError)
    async def calendar_error(_request: Request, exc: CalendarServiceError) -> JSONResponse:
        if isinstance(exc, CalendarTokenNotFound):
            status_code = 410
        elif isinstance(exc, InvalidCalendar):
            status_code = 422
        else:
            status_code = 400
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(SolverJobError)
    async def solver_job_error(_request: Request, exc: SolverJobError) -> JSONResponse:
        status_code = 404 if isinstance(exc, SolverJobNotFound) else 409
        if not isinstance(exc, (SolverJobNotFound, SolverJobConflict)):
            status_code = 400
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(DatabaseError)
    async def database_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "database_error",
                    "message": "The local database operation could not be completed",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The local request could not be completed",
                }
            },
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing(_request: Request) -> HTMLResponse:
        template = TEMPLATES.get_template("index.html")
        html = template.render(
            app_version=__version__,
            schema_version=VTOP_SCHEMA_VERSION,
            database_schema_version=database_schema_version,
            csrf_token=csrf_token,
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
