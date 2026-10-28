"""Persistent planning scenario, saved-result, comparison and export APIs."""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ffcs_studio.persistence.scenario_repository import ScenarioRepository
from ffcs_studio.services.scenario_service import ScenarioSourceService
from ffcs_studio.services.solver_jobs import SolverJobManager
from ffcs_studio.services.solver_service import SolverService
from ffcs_studio.solver.models import EvaluationMode
from ffcs_studio.web.routes.solver import (
    CourseScenarioRequest,
    CreditConstraintRequest,
    OccupiedIntervalRequest,
    ProvisionalPolicyRequest,
    RankingRequest,
    ScenarioRequest,
    _scenario_input,
)

router = APIRouter(prefix="/api/v1", tags=["phase-4-scenarios"])
ScenarioName = Annotated[str, Field(min_length=1, max_length=120)]


class SavedScenarioDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    campus: str = Field(default="", max_length=100)
    semester_label: str = Field(default="", max_length=200)
    calendar_id: str | None = Field(default=None, max_length=200)
    mode: EvaluationMode = EvaluationMode.EXPLORATORY
    courses: list[CourseScenarioRequest] = Field(default_factory=list, max_length=100)
    occupied_intervals: list[OccupiedIntervalRequest] = Field(default_factory=list, max_length=200)
    credit_constraints: CreditConstraintRequest = Field(default_factory=CreditConstraintRequest)
    ranking: RankingRequest = Field(default_factory=RankingRequest)
    provisional_policy: ProvisionalPolicyRequest = Field(default_factory=ProvisionalPolicyRequest)
    top_k: int = Field(default=20, ge=1, le=100)
    max_search_nodes: int | None = Field(default=2_000_000, ge=1_000, le=100_000_000)


class ScenarioCreateRequest(BaseModel):
    name: ScenarioName
    description: str = Field(default="", max_length=2000)
    document: SavedScenarioDocument


class ScenarioUpdateRequest(ScenarioCreateRequest):
    expected_revision: int = Field(ge=1)
    change_summary: str = Field(default="Scenario updated", min_length=1, max_length=500)


class ScenarioDuplicateRequest(BaseModel):
    name: ScenarioName


class RevisionActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class RestoreRequest(RevisionActionRequest):
    source_revision: int = Field(ge=1)


class SaveResultRequest(BaseModel):
    scenario_revision: int = Field(ge=1)
    job_id: str = Field(min_length=1, max_length=100)
    solver_result_id: str = Field(min_length=1, max_length=100)
    name: ScenarioName


@router.get("/scenarios")
async def list_scenarios(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_archived: bool = False,
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return {
        "api_version": "1.0",
        **repository.list(page=page, page_size=page_size, include_archived=include_archived),
    }


@router.post("/scenarios", status_code=201)
async def create_scenario(payload: ScenarioCreateRequest, request: Request) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    prepared = _prepare_document(payload.document, request)
    stored = repository.create(
        name=payload.name.strip(),
        description=payload.description,
        document=prepared["document"],
        source_references=prepared["source_references"],
        status=prepared["status"],
    )
    return _scenario_response(stored, request)


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _scenario_response(repository.get(scenario_id), request)


@router.put("/scenarios/{scenario_id}")
async def update_scenario(
    scenario_id: str, payload: ScenarioUpdateRequest, request: Request
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    prepared = _prepare_document(payload.document, request)
    stored = repository.update(
        scenario_id,
        expected_revision=payload.expected_revision,
        name=payload.name.strip(),
        description=payload.description,
        document=prepared["document"],
        source_references=prepared["source_references"],
        status=prepared["status"],
        change_summary=payload.change_summary,
    )
    return _scenario_response(stored, request)


@router.post("/scenarios/{scenario_id}/duplicate", status_code=201)
async def duplicate_scenario(
    scenario_id: str, payload: ScenarioDuplicateRequest, request: Request
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _scenario_response(repository.duplicate(scenario_id, name=payload.name.strip()), request)


@router.get("/scenarios/{scenario_id}/revisions")
async def scenario_revisions(scenario_id: str, request: Request) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return {"api_version": "1.0", "items": repository.revisions(scenario_id)}


@router.post("/scenarios/{scenario_id}/restore")
async def restore_scenario(
    scenario_id: str, payload: RestoreRequest, request: Request
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _scenario_response(
        repository.restore_revision(
            scenario_id,
            source_revision=payload.source_revision,
            expected_revision=payload.expected_revision,
        ),
        request,
    )


@router.post("/scenarios/{scenario_id}/archive")
async def archive_scenario(
    scenario_id: str, payload: RevisionActionRequest, request: Request
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _scenario_response(
        repository.archive(scenario_id, expected_revision=payload.expected_revision), request
    )


@router.post("/scenarios/{scenario_id}/unarchive")
async def unarchive_scenario(scenario_id: str, request: Request) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _scenario_response(repository.unarchive(scenario_id), request)


@router.delete("/scenarios/{scenario_id}", status_code=204)
async def delete_scenario(
    scenario_id: str, request: Request, expected_revision: int = Query(ge=1)
) -> Response:
    repository: ScenarioRepository = request.app.state.scenario_repository
    repository.delete(scenario_id, expected_revision=expected_revision)
    return Response(status_code=204)


@router.get("/scenarios/{scenario_id}/results")
async def list_saved_results(
    scenario_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return {
        "api_version": "1.0",
        **repository.list_results(scenario_id, page=page, page_size=page_size),
    }


@router.post("/scenarios/{scenario_id}/results", status_code=201)
async def save_result(
    scenario_id: str, payload: SaveResultRequest, request: Request
) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    scenario = repository.get(scenario_id)
    if int(scenario["current_revision"]) != payload.scenario_revision:
        from ffcs_studio.persistence.scenario_repository import ScenarioRevisionConflict

        raise ScenarioRevisionConflict("Reload the scenario before saving a result")
    prepared = _prepare_raw_document(scenario["document"], request)
    if prepared["solver_fingerprint"] is None:
        from ffcs_studio.persistence.scenario_repository import ScenarioRepositoryError

        raise ScenarioRepositoryError("The saved scenario is not solver-ready")
    jobs: SolverJobManager = request.app.state.solver_jobs
    snapshot = jobs.result_snapshot(payload.job_id, payload.solver_result_id)
    worker_scenario = snapshot["scenario"]
    if worker_scenario.fingerprint != prepared["solver_fingerprint"]:
        from ffcs_studio.persistence.scenario_repository import ScenarioRevisionConflict

        raise ScenarioRevisionConflict(
            "The solver result belongs to different scenario inputs; regenerate before saving"
        )
    result = snapshot["result"]
    source_references = {
        "calendar_id": worker_scenario.calendar_id,
        "scenario_fingerprint": worker_scenario.fingerprint,
        "offerings": [
            {
                "offering_id": course.offering_id,
                "revision_id": course.revision_id,
                "allocation_ids": list(assignment.allocation_ids),
            }
            for course, assignment in (
                (
                    next(
                        course
                        for course in worker_scenario.courses
                        if course.offering_id == assignment.offering_id
                    ),
                    assignment,
                )
                for assignment in result.assignments
            )
        ],
    }
    stored = repository.save_result(
        scenario_id=scenario_id,
        scenario_revision=payload.scenario_revision,
        name=payload.name.strip(),
        solver_result_id=result.result_id,
        solver_fingerprint=worker_scenario.fingerprint,
        calendar_id=worker_scenario.calendar_id,
        result=result.to_dict(),
        source_references=source_references,
        verification_status=result.verification_status,
    )
    return _result_response(stored, request)


@router.get("/saved-results/{saved_result_id}")
async def get_saved_result(saved_result_id: str, request: Request) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _result_response(repository.get_result(saved_result_id), request)


@router.post("/saved-results/{saved_result_id}/preferred")
async def prefer_saved_result(saved_result_id: str, request: Request) -> dict[str, Any]:
    repository: ScenarioRepository = request.app.state.scenario_repository
    return _result_response(repository.prefer_result(saved_result_id), request)


@router.get("/scenarios/{scenario_id}/export")
async def export_scenario(scenario_id: str, request: Request) -> Response:
    repository: ScenarioRepository = request.app.state.scenario_repository
    stored = repository.get(scenario_id)
    payload = {
        "export_schema_version": "1.0",
        "kind": "ffcs-studio-scenario",
        "scenario": {
            key: stored[key]
            for key in (
                "scenario_id",
                "name",
                "description",
                "current_revision",
                "status",
                "created_at",
                "updated_at",
            )
        },
        "document": stored["document"],
        "source_references": stored["source_references"],
    }
    return _download_json(payload, f"ffcs-scenario-{scenario_id}.json")


@router.get("/saved-results/{saved_result_id}/export.json")
async def export_saved_result_json(saved_result_id: str, request: Request) -> Response:
    repository: ScenarioRepository = request.app.state.scenario_repository
    stored = repository.get_result(saved_result_id)
    payload = {
        "export_schema_version": "1.0",
        "kind": "ffcs-studio-timetable",
        **stored,
    }
    return _download_json(payload, f"ffcs-timetable-{saved_result_id}.json")


@router.get("/saved-results/{saved_result_id}/export.csv")
async def export_saved_result_csv(saved_result_id: str, request: Request) -> Response:
    repository: ScenarioRepository = request.app.state.scenario_repository
    stored = repository.get_result(saved_result_id)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["Day", "Start", "End", "Course", "Component", "Faculty", "Venue", "Slot"])
    for assignment in stored["result"].get("assignments", []):
        for meeting in assignment.get("meetings", []):
            writer.writerow(
                [
                    _csv_safe(meeting.get("day_name", "")),
                    meeting.get("start_time", ""),
                    meeting.get("end_time", ""),
                    _csv_safe(assignment.get("course_code", "")),
                    _csv_safe(meeting.get("component_type", "")),
                    _csv_safe(meeting.get("faculty", "")),
                    _csv_safe(meeting.get("venue", "")),
                    _csv_safe(meeting.get("slot", "")),
                ]
            )
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ffcs-timetable-{saved_result_id}.csv"'
        },
    )


def _prepare_document(document: SavedScenarioDocument, request: Request) -> dict[str, Any]:
    return _prepare_raw_document(document.model_dump(mode="json"), request)


def _prepare_raw_document(document: dict[str, Any], request: Request) -> dict[str, Any]:
    source_service: ScenarioSourceService = request.app.state.scenario_source_service
    normalized, _references, _issues, _status = source_service.prepare(document, solver_ready=False)
    solver_ready = False
    fingerprint: str | None = None
    if (
        normalized.get("campus")
        and normalized.get("semester_label")
        and normalized.get("calendar_id")
        and normalized.get("courses")
    ):
        solver_payload = {
            key: value for key, value in normalized.items() if key != "schema_version"
        }
        parsed = ScenarioRequest.model_validate(solver_payload)
        solver: SolverService = request.app.state.solver_service
        validation = solver.validate(_scenario_input(parsed))
        solver_ready = validation.valid
        fingerprint = validation.scenario.fingerprint if validation.scenario else None
    normalized, references, issues, status = source_service.prepare(
        normalized, solver_ready=solver_ready
    )
    return {
        "document": normalized,
        "source_references": references,
        "compatibility": issues,
        "status": status,
        "solver_ready": solver_ready,
        "solver_fingerprint": fingerprint,
    }


def _scenario_response(stored: dict[str, Any], request: Request) -> dict[str, Any]:
    source_service: ScenarioSourceService = request.app.state.scenario_source_service
    return {
        "api_version": "1.0",
        **stored,
        "compatibility": source_service.compatibility(stored["document"]),
    }


def _result_response(stored: dict[str, Any], request: Request) -> dict[str, Any]:
    source_service: ScenarioSourceService = request.app.state.scenario_source_service
    return {
        "api_version": "1.0",
        **stored,
        "compatibility": source_service.result_compatibility(stored),
    }


def _download_json(payload: dict[str, Any], filename: str) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _csv_safe(value: object) -> str:
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
