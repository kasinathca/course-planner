"""Versioned degree-planning and recovery API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ffcs_studio.persistence.degree_repository import DegreeRepository
from ffcs_studio.services.degree_service import DegreeService, DegreeServiceError
from ffcs_studio.services.solver_service import SolverService
from ffcs_studio.web.routes.solver import ScenarioRequest, _scenario_input

router = APIRouter(prefix="/api/v1", tags=["degree"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportValidateRequest(StrictModel):
    kind: Literal["curriculum", "legacy_v6"]
    filename: str = Field(min_length=1, max_length=255)
    source_sequence: int = Field(default=1, ge=1, le=1000)
    document: dict[str, Any]


class PreviewRequest(StrictModel):
    validation_id: str = Field(min_length=1, max_length=100)


class CommitRequest(StrictModel):
    preview_id: str = Field(min_length=1, max_length=100)


class LegacyActivationRequest(StrictModel):
    curriculum_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=120)


class PlanRecordRequest(StrictModel):
    record_id: str = Field(min_length=1, max_length=160)
    course_id: str = Field(min_length=1, max_length=240)
    semester: int = Field(ge=0, le=10)
    status: Literal["planned", "tentative", "enrolled", "completed", "withdrawn", "failed"]
    intended_category: str | None = Field(default=None, max_length=32)
    notes: str = Field(default="", max_length=1000)
    source: Literal["official", "user_supplied", "legacy", "manual", "derived", "unknown"] = (
        "manual"
    )
    attempt: int = Field(default=1, ge=1, le=100)
    offering_id: int | None = Field(default=None, ge=1)


class PlanDocumentRequest(StrictModel):
    programme_code: str = Field(min_length=1, max_length=100)
    curriculum_revision: str = Field(min_length=1, max_length=100)
    records: list[PlanRecordRequest] = Field(default_factory=list, max_length=1000)
    settings: dict[str, Any] = Field(default_factory=dict)
    semester_labels: dict[str, str] = Field(default_factory=dict)


class PlanCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    curriculum_id: str = Field(min_length=1, max_length=160)
    document: PlanDocumentRequest
    source_snapshot_id: str | None = Field(default=None, max_length=128)


class PlanUpdateRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    change_summary: str = Field(min_length=1, max_length=500)
    document: PlanDocumentRequest


class ProgressPreviewRequest(StrictModel):
    curriculum_id: str = Field(min_length=1, max_length=160)
    document: PlanDocumentRequest


class RestoreRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    source_revision: int = Field(ge=1)


class DuplicateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)


class ArchiveRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class TransferRequest(StrictModel):
    semester: int = Field(ge=1, le=10)
    campus: str = Field(min_length=1, max_length=120)
    semester_label: str = Field(min_length=1, max_length=200)
    calendar_id: str = Field(min_length=1, max_length=160)
    roles: dict[str, Literal["required", "optional", "excluded"]] = Field(default_factory=dict)


class TransferCommitRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    preview: dict[str, Any]


class AvailabilityRequest(StrictModel):
    campus: str = Field(min_length=1, max_length=120)
    semester_label: str = Field(min_length=1, max_length=200)
    offering_revision_id: int = Field(ge=1)
    allocation_id: int = Field(ge=1)
    state: Literal[
        "available",
        "full",
        "unavailable",
        "registered",
        "registration_failed",
        "waitlisted",
        "pending",
        "unknown",
    ]
    provenance: Literal["manual", "user_supplied", "imported_vtop"] = "manual"
    note: str = Field(default="", max_length=1000)
    captured_at: datetime


class RecoveryRequestModel(StrictModel):
    intended: dict[str, str] = Field(default_factory=dict)
    options: dict[str, list[dict[str, Any]]]
    registered_locks: dict[str, str] = Field(default_factory=dict)
    must_take: list[str] = Field(default_factory=list)
    blocked_allocations: list[int] = Field(default_factory=list)
    priority: dict[str, int] = Field(default_factory=dict)
    scenario_id: str | None = None
    scenario_revision: int | None = Field(default=None, ge=1)
    source_revision_fingerprint: str = Field(default="manual-preview", max_length=200)
    max_nodes: int = Field(default=200_000, ge=1, le=2_000_000)
    top_k: int = Field(default=20, ge=1, le=100)


class ScenarioRecoveryRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    intended: dict[str, str]
    unlock_courses: list[str] = Field(default_factory=list)
    max_nodes: int = Field(default=200_000, ge=1, le=2_000_000)
    top_k: int = Field(default=20, ge=1, le=100)


@router.get("/programmes")
async def programmes(request: Request) -> dict[str, Any]:
    return {"items": _repository(request).list_programmes()}


@router.get("/curricula")
async def curricula(request: Request) -> dict[str, Any]:
    return {"items": _repository(request).list_curricula()}


@router.get("/curricula/{curriculum_id}")
async def curriculum(request: Request, curriculum_id: str) -> dict[str, Any]:
    return _repository(request).get_curriculum(curriculum_id)


@router.post("/degree/imports/validate")
async def validate_import(request: Request, payload: ImportValidateRequest) -> dict[str, Any]:
    if payload.kind == "curriculum":
        return _service(request).validate_curriculum(payload.document, filename=payload.filename)
    return _service(request).validate_legacy(
        payload.document, filename=payload.filename, source_sequence=payload.source_sequence
    )


@router.post("/degree/imports/preview")
async def preview_import(request: Request, payload: PreviewRequest) -> dict[str, Any]:
    return _service(request).preview(payload.validation_id)


@router.post("/degree/imports/commit")
async def commit_import(request: Request, payload: CommitRequest) -> dict[str, Any]:
    return _service(request).commit(payload.preview_id)


@router.get("/degree/imports/legacy")
async def legacy_imports(request: Request) -> dict[str, Any]:
    return {"items": _repository(request).list_legacy_imports()}


@router.get("/degree/imports/legacy/compare")
async def compare_legacy(request: Request, left: str, right: str) -> dict[str, Any]:
    return _service(request).compare_legacy(left, right)


@router.post("/degree/imports/legacy/{snapshot_id}/activate", status_code=201)
async def activate_legacy(
    request: Request,
    snapshot_id: str,
    payload: LegacyActivationRequest,
) -> dict[str, Any]:
    return _service(request).activate_legacy_snapshot(
        snapshot_id=snapshot_id,
        curriculum_id=payload.curriculum_id,
        name=payload.name,
    )


@router.get("/degree/catalog")
async def catalogue(
    request: Request,
    curriculum_id: str,
    query: str = "",
    category: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    return _repository(request).list_catalogue(
        curriculum_id, query=query, category=category, page=page, page_size=page_size
    )


@router.get("/degree/catalog/{catalogue_course_id}")
async def catalogue_course(request: Request, catalogue_course_id: str) -> dict[str, Any]:
    return _repository(request).get_catalogue_course(catalogue_course_id)


@router.get("/degree/plans")
async def plans(request: Request, include_archived: bool = False) -> dict[str, Any]:
    return {"items": _repository(request).list_plans(include_archived=include_archived)}


@router.post("/degree/plans", status_code=201)
async def create_plan(request: Request, payload: PlanCreateRequest) -> dict[str, Any]:
    return _repository(request).create_plan(
        name=payload.name,
        curriculum_id=payload.curriculum_id,
        document=payload.document.model_dump(),
        source_snapshot_id=payload.source_snapshot_id,
    )


@router.get("/degree/plans/{plan_id}")
async def get_plan(
    request: Request, plan_id: str, revision: int | None = Query(default=None, ge=1)
) -> dict[str, Any]:
    return _repository(request).get_plan(plan_id, revision=revision)


@router.put("/degree/plans/{plan_id}")
async def update_plan(request: Request, plan_id: str, payload: PlanUpdateRequest) -> dict[str, Any]:
    return _repository(request).update_plan(
        plan_id,
        expected_revision=payload.expected_revision,
        name=payload.name,
        document=payload.document.model_dump(),
        change_summary=payload.change_summary,
    )


@router.get("/degree/plans/{plan_id}/revisions")
async def plan_revisions(request: Request, plan_id: str) -> dict[str, Any]:
    return {"items": _repository(request).revisions(plan_id)}


@router.post("/degree/plans/{plan_id}/restore")
async def restore_plan(request: Request, plan_id: str, payload: RestoreRequest) -> dict[str, Any]:
    return _repository(request).restore_plan(
        plan_id,
        source_revision=payload.source_revision,
        expected_revision=payload.expected_revision,
    )


@router.post("/degree/plans/{plan_id}/duplicate", status_code=201)
async def duplicate_plan(
    request: Request, plan_id: str, payload: DuplicateRequest
) -> dict[str, Any]:
    return _repository(request).duplicate_plan(plan_id, name=payload.name)


@router.post("/degree/plans/{plan_id}/archive")
async def archive_plan(request: Request, plan_id: str, payload: ArchiveRequest) -> dict[str, Any]:
    return _repository(request).archive_plan(plan_id, expected_revision=payload.expected_revision)


@router.get("/degree/plans/{plan_id}/compare")
async def compare_plan(
    request: Request,
    plan_id: str,
    left_revision: int = Query(ge=1),
    right_revision: int = Query(ge=1),
) -> dict[str, Any]:
    return _service(request).compare_plans(plan_id, left_revision, right_revision)


@router.get("/degree/plans/{plan_id}/progress")
async def progress(
    request: Request, plan_id: str, revision: int | None = Query(default=None, ge=1)
) -> dict[str, Any]:
    return _service(request).progress(plan_id, revision=revision)


@router.post("/degree/progress/preview")
async def progress_preview(request: Request, payload: ProgressPreviewRequest) -> dict[str, Any]:
    return _service(request).progress_document(payload.curriculum_id, payload.document.model_dump())


@router.get("/degree/plans/{plan_id}/recommendations")
async def recommendations(
    request: Request, plan_id: str, semester: int = Query(ge=1, le=10), offered_only: bool = False
) -> dict[str, Any]:
    return _service(request).recommendations(plan_id, semester=semester, offered_only=offered_only)


@router.post("/degree/plans/{plan_id}/semester-transfer/preview")
async def transfer_preview(
    request: Request, plan_id: str, payload: TransferRequest
) -> dict[str, Any]:
    return _service(request).transfer_preview(plan_id, **payload.model_dump())


@router.post("/degree/plans/{plan_id}/semester-transfer/commit", status_code=201)
async def transfer_commit(
    request: Request, plan_id: str, payload: TransferCommitRequest
) -> dict[str, Any]:
    return _service(request).transfer_commit(plan_id, name=payload.name, preview=payload.preview)


@router.get("/recovery/availability")
async def availability(
    request: Request, campus: str = "", semester_label: str = ""
) -> dict[str, Any]:
    return {
        "items": _repository(request).list_availability(
            campus=campus, semester_label=semester_label
        )
    }


@router.post("/recovery/availability", status_code=201)
async def set_availability(request: Request, payload: AvailabilityRequest) -> dict[str, Any]:
    return _repository(request).set_availability(**payload.model_dump(mode="json"))


@router.post("/recovery/availability/{availability_id}/clear")
async def clear_availability(request: Request, availability_id: str) -> dict[str, Any]:
    return _repository(request).clear_availability(availability_id)


@router.post("/recovery/scenarios", status_code=201)
async def run_recovery(request: Request, payload: RecoveryRequestModel) -> dict[str, Any]:
    return _service(request).recovery(payload.model_dump())


@router.post("/recovery/scenarios/{scenario_id}/run", status_code=201)
async def run_saved_scenario_recovery(
    request: Request,
    scenario_id: str,
    payload: ScenarioRecoveryRequest,
) -> dict[str, Any]:
    stored = request.app.state.scenario_repository.get(scenario_id)
    if int(stored["current_revision"]) != payload.expected_revision:
        raise DegreeServiceError("Saved scenario changed before recovery")
    scenario_request = ScenarioRequest.model_validate(stored["document"])
    solver: SolverService = request.app.state.solver_service
    validation = solver.validate(_scenario_input(scenario_request))
    if not validation.valid or validation.scenario is None:
        messages = "; ".join(item.message for item in validation.issues)
        raise DegreeServiceError(f"Saved scenario is not recovery-ready: {messages}")
    return _service(request).recovery_from_snapshot(
        stored_scenario=stored,
        snapshot=validation.scenario,
        intended=payload.intended,
        unlock_courses=set(payload.unlock_courses),
        max_nodes=payload.max_nodes,
        top_k=payload.top_k,
    )


@router.post("/recovery/jobs", status_code=202)
async def start_recovery_job(request: Request, payload: RecoveryRequestModel) -> dict[str, Any]:
    result: dict[str, Any] = request.app.state.recovery_jobs.start(payload.model_dump())
    return result


@router.get("/recovery/jobs/{job_id}")
async def recovery_job_status(request: Request, job_id: str) -> dict[str, Any]:
    result: dict[str, Any] = request.app.state.recovery_jobs.status(job_id)
    return result


@router.post("/recovery/jobs/{job_id}/cancel")
async def cancel_recovery_job(request: Request, job_id: str) -> dict[str, Any]:
    result: dict[str, Any] = request.app.state.recovery_jobs.cancel(job_id)
    return result


def _repository(request: Request) -> DegreeRepository:
    repository: DegreeRepository = request.app.state.degree_repository
    return repository


def _service(request: Request) -> DegreeService:
    service: DegreeService = request.app.state.degree_service
    return service
