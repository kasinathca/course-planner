"""Validated upload, preview, commit, and import history routes."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ffcs_studio.importers.vtop_csv import csv_metadata_from_mapping
from ffcs_studio.services.catalog_service import CatalogService
from ffcs_studio.services.import_service import ImportService
from ffcs_studio.validation import ValidationIssue
from ffcs_studio.web.api_models import (
    CommitRequest,
    CommitResponse,
    IssueResponse,
    PaginatedResponse,
    PreviewRequest,
    PreviewResponse,
    ValidationResponse,
)

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


@router.post("/validate", response_model=None)
async def validate_upload(request: Request) -> ValidationResponse | JSONResponse:
    service: ImportService = request.app.state.import_service
    filename = request.headers.get("x-ffcs-filename", "")
    content_type = request.headers.get("content-type", "")
    csv_metadata = None
    if content_type.split(";", 1)[0].strip().lower() in {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
    }:
        metadata_mapping, metadata_error = _csv_metadata_headers(request)
        if metadata_error is not None:
            return _validation_failure((metadata_error,))
        csv_metadata, issues = csv_metadata_from_mapping(metadata_mapping, origin="user_supplied")
        if issues:
            return _validation_failure(issues)
    content = await request.body()
    outcome = service.validate_upload(
        content,
        filename=filename,
        content_type=content_type,
        csv_metadata=csv_metadata,
    )
    if not outcome.result.valid or outcome.result.prepared is None:
        return _validation_failure(outcome.result.issues)
    prepared = outcome.result.prepared
    return ValidationResponse(
        valid=True,
        validation_id=outcome.validation_id or "",
        expires_at=outcome.expires_at or "",
        source_format=prepared.source_format,
        filename=prepared.original_filename,
        campus=prepared.snapshot.campus,
        semester_label=prepared.snapshot.semester_label,
        course_count=prepared.course_count,
        allocation_count=prepared.allocation_count,
        issues=[_issue(issue) for issue in prepared.issues],
    )


@router.post("/preview", response_model=PreviewResponse)
async def preview_import(payload: PreviewRequest, request: Request) -> PreviewResponse:
    service: ImportService = request.app.state.import_service
    outcome = service.preview(payload.validation_id)
    prepared = outcome.prepared
    return PreviewResponse(
        preview_id=outcome.preview_id,
        expires_at=outcome.expires_at,
        filename=prepared.original_filename,
        campus=prepared.snapshot.campus,
        semester_label=prepared.snapshot.semester_label,
        course_count=prepared.course_count,
        allocation_count=prepared.allocation_count,
        issues=[_issue(issue) for issue in prepared.issues],
        reconciliation=outcome.report.to_dict(),
    )


@router.post("/commit", response_model=CommitResponse)
async def commit_import(payload: CommitRequest, request: Request) -> CommitResponse:
    service: ImportService = request.app.state.import_service
    outcome = service.commit(payload.preview_id)
    return CommitResponse(**asdict(outcome))


@router.get("", response_model=PaginatedResponse)
async def list_imports(
    request: Request,
    page: int = Query(1, ge=1, le=1_000_000),
    page_size: int = Query(25, ge=1, le=100),
) -> PaginatedResponse:
    catalog: CatalogService = request.app.state.catalog_service
    return PaginatedResponse(**catalog.list_imports(page=page, page_size=page_size))


@router.get("/{import_id}", response_model=None)
async def import_detail(import_id: str, request: Request) -> dict[str, object] | JSONResponse:
    catalog: CatalogService = request.app.state.catalog_service
    result = catalog.import_detail(import_id)
    if result is None:
        return _not_found("import_not_found", "Import snapshot was not found")
    return {"api_version": "1.0", **result}


@router.get("/{import_id}/diff", response_model=None)
async def import_diff(import_id: str, request: Request) -> dict[str, object] | JSONResponse:
    catalog: CatalogService = request.app.state.catalog_service
    result = catalog.import_diff(import_id)
    if result is None:
        return _not_found("import_not_found", "Import snapshot was not found")
    return {"api_version": "1.0", "items": result}


def _csv_metadata_headers(request: Request) -> tuple[dict[str, Any], ValidationIssue | None]:
    sidecar = request.headers.get("x-ffcs-metadata")
    if sidecar:
        try:
            parsed = json.loads(sidecar)
        except json.JSONDecodeError as exc:
            return {}, ValidationIssue("error", "invalid_metadata_sidecar", "/metadata", str(exc))
        if not isinstance(parsed, dict):
            return {}, ValidationIssue(
                "error", "invalid_metadata_sidecar", "/metadata", "metadata must be an object"
            )
        return parsed, None
    return (
        {
            "campus": request.headers.get("x-ffcs-campus"),
            "semester_label": request.headers.get("x-ffcs-semester"),
            "captured_at": request.headers.get("x-ffcs-captured-at"),
        },
        None,
    )


def _issue(issue: ValidationIssue) -> IssueResponse:
    return IssueResponse(
        level=issue.level,
        code=issue.code,
        path=issue.path,
        message=issue.message,
    )


def _validation_failure(issues: tuple[ValidationIssue, ...]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_failed",
                "message": "Uploaded data did not pass validation",
                "issues": [asdict(issue) for issue in issues],
            }
        },
    )


def _not_found(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": {"code": code, "message": message}})
