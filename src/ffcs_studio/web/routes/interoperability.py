"""Course interchange, scenario import, and managed backup APIs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ffcs_studio.domain.models import ImportSnapshot
from ffcs_studio.importers.models import build_prepared_import
from ffcs_studio.persistence.scenario_repository import ScenarioNotFound
from ffcs_studio.services.backup_service import BackupService
from ffcs_studio.services.import_service import ImportService
from ffcs_studio.services.interoperability import (
    SemesterExportService,
    parse_ffcsinator_typescript,
)
from ffcs_studio.services.scenario_import import ScenarioImportService
from ffcs_studio.validation import ValidationIssue
from ffcs_studio.web.routes.scenarios import SavedScenarioDocument, _prepare_raw_document

router = APIRouter(prefix="/api/v1", tags=["phase-6-interoperability"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LegacyImportRequest(StrictModel):
    filename: str = Field(min_length=1, max_length=120)
    campus: str = Field(min_length=1, max_length=100)
    semester_label: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)


class ScenarioValidateRequest(StrictModel):
    document: dict[str, Any]


class TokenRequest(StrictModel):
    validation_id: str = Field(min_length=1, max_length=100)


class ScenarioCommitRequest(StrictModel):
    preview_id: str = Field(min_length=1, max_length=100)
    choice: Literal["create_new", "duplicate"]
    name: str = Field(min_length=1, max_length=120)


class BackupCreateRequest(StrictModel):
    label: str = Field(default="manual", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9 _-]+$")


class BackupRestoreRequest(StrictModel):
    backup_id: str = Field(min_length=1, max_length=255)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation: str = Field(max_length=20)


@router.get("/data/export/{format_name}")
async def export_semester(
    format_name: Literal["json", "csv", "csv-metadata", "xlsx", "ffcsinator"],
    request: Request,
    campus: str = Query(min_length=1, max_length=100),
    semester_label: str = Query(min_length=1, max_length=200),
) -> Response:
    service: SemesterExportService = request.app.state.semester_exports
    snapshot = service.snapshot(campus=campus, semester_label=semester_label)
    stem = _safe_stem(f"ffcs-{campus}-{semester_label}")
    if format_name == "json":
        return _download(service.canonical_json(snapshot), "application/json", f"{stem}.json")
    if format_name in {"csv", "csv-metadata"}:
        csv_content, metadata = service.csv_and_sidecar(snapshot)
        return _download(
            csv_content if format_name == "csv" else metadata,
            "text/csv" if format_name == "csv" else "application/json",
            f"{stem}.csv" if format_name == "csv" else f"{stem}.metadata.json",
        )
    if format_name == "xlsx":
        return _download(
            service.xlsx(snapshot),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{stem}.xlsx",
        )
    return _download(service.ffcsinator_zip(snapshot), "application/zip", f"{stem}-ffcsinator.zip")


@router.post("/data/ffcsinator/convert")
async def convert_legacy(payload: LegacyImportRequest, request: Request) -> dict[str, Any]:
    canonical, diagnostics = parse_ffcsinator_typescript(
        payload.content,
        filename=payload.filename,
        campus=payload.campus,
        semester_label=payload.semester_label,
    )
    snapshot = ImportSnapshot.from_mapping(canonical)
    issues = tuple(
        ValidationIssue(
            level=diagnostic["level"],
            code=diagnostic["code"],
            path="/courses",
            message=diagnostic["message"],
        )
        for diagnostic in diagnostics
    )
    prepared = build_prepared_import(
        source_format="json",
        source_kind="legacy-ffcsinator",
        metadata_origin="bounded_typescript_adapter",
        filename=payload.filename,
        raw_bytes=payload.content.encode("utf-8"),
        snapshot=snapshot,
        issues=issues,
    )
    import_service: ImportService = request.app.state.import_service
    outcome = import_service.validate_prepared(prepared)
    return {
        "canonical": canonical,
        "diagnostics": diagnostics,
        "validation_id": outcome.validation_id,
        "expires_at": outcome.expires_at,
        "course_count": prepared.course_count,
        "allocation_count": prepared.allocation_count,
        "source": prepared.source_kind,
    }


@router.post("/scenarios/import/validate")
async def validate_scenario_import(
    payload: ScenarioValidateRequest, request: Request
) -> dict[str, Any]:
    service: ScenarioImportService = request.app.state.scenario_imports
    validation_id, expires_at, record = service.validate(payload.document)
    SavedScenarioDocument.model_validate(record.document)
    return {
        "validation_id": validation_id,
        "expires_at": expires_at,
        "name": record.original_name,
        "course_count": len(record.document.get("courses", [])),
        "original_scenario_id": record.original_scenario_id,
    }


@router.post("/scenarios/import/preview")
async def preview_scenario_import(payload: TokenRequest, request: Request) -> dict[str, Any]:
    service: ScenarioImportService = request.app.state.scenario_imports
    preview_id, expires_at, record = service.preview(payload.validation_id)
    document = SavedScenarioDocument.model_validate(record.document).model_dump(mode="json")
    prepared = _prepare_raw_document(document, request)
    conflict = False
    if record.original_scenario_id:
        try:
            request.app.state.scenario_repository.get(record.original_scenario_id)
            conflict = True
        except ScenarioNotFound:
            pass
    return {
        "preview_id": preview_id,
        "expires_at": expires_at,
        "name": record.original_name,
        "document": prepared["document"],
        "compatibility": prepared["compatibility"],
        "status": prepared["status"],
        "solver_ready": prepared["solver_ready"],
        "identity_conflict": conflict,
        "requires_choice": True,
    }


@router.post("/scenarios/import/commit", status_code=201)
async def commit_scenario_import(
    payload: ScenarioCommitRequest, request: Request
) -> dict[str, Any]:
    service: ScenarioImportService = request.app.state.scenario_imports
    record = service.consume(payload.preview_id)
    document = SavedScenarioDocument.model_validate(record.document).model_dump(mode="json")
    prepared = _prepare_raw_document(document, request)
    stored = request.app.state.scenario_repository.create(
        name=payload.name.strip(),
        description=record.original_description,
        document=prepared["document"],
        source_references={
            **prepared["source_references"],
            "imported_original_scenario_id": record.original_scenario_id,
            "import_choice": payload.choice,
        },
        status=prepared["status"],
        change_summary=f"Imported scenario as {payload.choice.replace('_', ' ')}",
    )
    return {**stored, "compatibility": prepared["compatibility"]}


@router.get("/backups")
async def list_backups(request: Request) -> dict[str, Any]:
    service: BackupService = request.app.state.backup_service
    return {"items": service.list()}


@router.post("/backups", status_code=201)
async def create_backup(payload: BackupCreateRequest, request: Request) -> dict[str, Any]:
    service: BackupService = request.app.state.backup_service
    return service.create(payload.label)


@router.get("/backups/{backup_id}/download")
async def download_backup(backup_id: str, request: Request) -> FileResponse:
    service: BackupService = request.app.state.backup_service
    path = service.file(backup_id)
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=path.name)


@router.post("/backups/restore")
async def restore_backup(payload: BackupRestoreRequest, request: Request) -> dict[str, Any]:
    service: BackupService = request.app.state.backup_service

    def quiesce() -> None:
        request.app.state.solver_jobs.shutdown()
        request.app.state.recovery_jobs.shutdown()

    def reinitialize() -> None:
        from ffcs_studio.services.recovery_jobs import RecoveryJobManager
        from ffcs_studio.services.solver_jobs import SolverJobManager

        settings = request.app.state.settings
        request.app.state.solver_jobs = SolverJobManager(
            max_workers=settings.solver_max_workers,
            cancel_grace_seconds=settings.solver_cancel_grace_seconds,
        )
        request.app.state.recovery_jobs = RecoveryJobManager(
            max_workers=settings.solver_max_workers,
            cancel_grace_seconds=settings.solver_cancel_grace_seconds,
        )

    return service.restore(
        payload.backup_id,
        expected_sha256=payload.expected_sha256,
        confirmation=payload.confirmation,
        quiesce=quiesce,
        reinitialize=reinitialize,
    )


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _safe_stem(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "-_" else "-" for character in value
    )[:160]
