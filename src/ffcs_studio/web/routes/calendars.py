"""Phase 2 calendar, resolution, conflict and component inspection APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ffcs_studio.domain.component_rules import CurriculumType, allocation_type
from ffcs_studio.domain.conflicts import check_conflicts
from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.repositories import Repository
from ffcs_studio.services.calendar_service import CalendarService
from ffcs_studio.services.registration_candidates import preview_candidates
from ffcs_studio.services.slot_resolution import resolve_slot_expression

router = APIRouter(prefix="/api/v1", tags=["phase-2"])


class CalendarPreviewRequest(BaseModel):
    validation_id: str = Field(min_length=20, max_length=200)


class CalendarCommitRequest(BaseModel):
    preview_id: str = Field(min_length=20, max_length=200)
    make_active: bool = True


class SlotResolveRequest(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=500)


class ConflictRequest(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=200)
    left: str = Field(min_length=1, max_length=500)
    right: str = Field(min_length=1, max_length=500)


@router.get("/calendars")
async def calendars(request: Request) -> dict[str, object]:
    repository: CalendarRepository = request.app.state.calendar_repository
    return {"api_version": "1.0", "items": repository.list()}


@router.post("/calendars/validate")
async def validate_calendar(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    service: CalendarService = request.app.state.calendar_service
    return {"api_version": "1.0", **service.validate(payload)}


@router.post("/calendars/preview")
async def preview_calendar(payload: CalendarPreviewRequest, request: Request) -> dict[str, Any]:
    service: CalendarService = request.app.state.calendar_service
    return {"api_version": "1.0", **service.preview(payload.validation_id)}


@router.post("/calendars/commit")
async def commit_calendar(payload: CalendarCommitRequest, request: Request) -> dict[str, Any]:
    service: CalendarService = request.app.state.calendar_service
    return {
        "api_version": "1.0",
        **service.commit(payload.preview_id, make_active=payload.make_active),
    }


@router.post("/calendars/{calendar_id}/select", response_model=None)
async def select_calendar(calendar_id: str, request: Request) -> dict[str, object] | JSONResponse:
    repository: CalendarRepository = request.app.state.calendar_repository
    if not repository.select_active(calendar_id):
        return _calendar_not_found()
    return {"api_version": "1.0", "calendar_id": calendar_id, "active": True}


@router.get("/calendars/{calendar_id}", response_model=None)
async def calendar_detail(calendar_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    repository: CalendarRepository = request.app.state.calendar_repository
    calendar = repository.get(calendar_id)
    if calendar is None:
        return _calendar_not_found()
    return {
        "api_version": "1.0",
        "calendar_id": calendar.calendar_id,
        "campus": calendar.campus,
        "semester_label": calendar.semester_label,
        "profile_name": calendar.profile_name,
        "version": calendar.version,
        "timezone": calendar.timezone,
        "verification_status": calendar.verification_status.value,
        "evidence": {
            "kind": calendar.evidence.kind,
            "reference": calendar.evidence.reference,
            "reviewed_by": calendar.evidence.reviewed_by,
            "reviewed_at": calendar.evidence.reviewed_at,
            "notes": calendar.evidence.notes,
        },
        "slots": {
            code: [interval.to_dict() for interval in slot.intervals]
            for code, slot in calendar.slots.items()
        },
    }


@router.post("/slots/resolve", response_model=None)
async def resolve_slots(
    payload: SlotResolveRequest, request: Request
) -> dict[str, Any] | JSONResponse:
    repository: CalendarRepository = request.app.state.calendar_repository
    calendar = repository.get(payload.calendar_id)
    if calendar is None:
        return _calendar_not_found()
    return {
        "api_version": "1.0",
        "calendar_id": calendar.calendar_id,
        **resolve_slot_expression(payload.expression, calendar).to_dict(),
    }


@router.post("/conflicts/check", response_model=None)
async def conflicts(payload: ConflictRequest, request: Request) -> dict[str, Any] | JSONResponse:
    repository: CalendarRepository = request.app.state.calendar_repository
    calendar = repository.get(payload.calendar_id)
    if calendar is None:
        return _calendar_not_found()
    left = resolve_slot_expression(payload.left, calendar)
    right = resolve_slot_expression(payload.right, calendar)
    return {
        "api_version": "1.0",
        "calendar_id": calendar.calendar_id,
        "left": left.to_dict(),
        "right": right.to_dict(),
        "report": check_conflicts(left, right).to_dict(),
    }


@router.get("/offerings/{offering_id}/components", response_model=None)
async def components(offering_id: int, request: Request) -> dict[str, Any] | JSONResponse:
    repository: Repository = request.app.state.repository
    detail = repository.offering_detail(offering_id)
    allocations = repository.offering_allocations(offering_id)
    if detail is None or allocations is None:
        return _offering_not_found()
    return {
        "api_version": "1.0",
        "offering_id": offering_id,
        "revision_id": detail["revision_id"],
        "curriculum_type": "unknown",
        "curriculum_type_status": "not_supplied_by_phase_1_source",
        "items": [
            {
                **item,
                "allocation_type": allocation_type(str(item["course_type"])).value,
                "classification_status": (
                    "recognized"
                    if allocation_type(str(item["course_type"])).value != "unknown"
                    else "needs_review"
                ),
            }
            for item in allocations
        ],
    }


@router.get("/offerings/{offering_id}/registration-options", response_model=None)
async def registration_options(
    offering_id: int,
    request: Request,
    curriculum_type: CurriculumType = CurriculumType.UNKNOWN,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any] | JSONResponse:
    repository: Repository = request.app.state.repository
    calendars_repository: CalendarRepository = request.app.state.calendar_repository
    detail = repository.offering_detail(offering_id)
    allocations = repository.offering_allocations(offering_id)
    if detail is None or allocations is None:
        return _offering_not_found()
    preview = preview_candidates(
        allocations,
        curriculum_type,
        calendars_repository.pairing_states(int(str(detail["revision_id"]))),
        limit=limit,
    )
    return {
        "api_version": "1.0",
        "offering_id": offering_id,
        "revision_id": detail["revision_id"],
        "curriculum_type": curriculum_type.value,
        "items": [candidate.to_dict() for candidate in preview.items],
        "bounded_at": limit,
        "truncated": preview.truncated,
    }


def _calendar_not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "calendar_not_found", "message": "Calendar was not found"}},
    )


def _offering_not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "offering_not_found", "message": "Offering was not found"}},
    )
