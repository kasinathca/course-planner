"""Phase 3 scenario validation, process jobs, results and exact-count APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ffcs_studio.domain.component_rules import CurriculumType
from ffcs_studio.services.solver_jobs import SolverJobManager
from ffcs_studio.services.solver_service import (
    RequestedCourse,
    RequestedOccupiedInterval,
    SolverScenarioInput,
    SolverService,
)
from ffcs_studio.solver.models import (
    CourseRole,
    CreditConstraints,
    CreditSource,
    EvaluationMode,
    RankingPolicy,
)

router = APIRouter(prefix="/api/v1/solver", tags=["phase-3-solver"])
CreditValue = Annotated[Decimal, Field(ge=0, max_digits=8, decimal_places=3)]


class CourseScenarioRequest(BaseModel):
    offering_id: int = Field(gt=0)
    role: CourseRole
    curriculum_type: CurriculumType
    curriculum_source: CreditSource = CreditSource.UNKNOWN
    credits: CreditValue | None = None
    credit_source: CreditSource = CreditSource.UNKNOWN
    priority_tier: int = Field(default=1, ge=1, le=20)
    locked_allocation_ids: list[int] = Field(default_factory=list, max_length=100)
    locked_faculties: list[str] = Field(default_factory=list, max_length=100)
    forbidden_allocation_ids: list[int] = Field(default_factory=list, max_length=100)
    forbidden_faculties: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("locked_allocation_ids", "forbidden_allocation_ids")
    @classmethod
    def positive_allocation_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("allocation identifiers must be positive")
        return values


class OccupiedIntervalRequest(BaseModel):
    day: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)
    label: str = Field(default="manual commitment", min_length=1, max_length=100)

    @field_validator("end_minute")
    @classmethod
    def end_after_start(cls, value: int, info: Any) -> int:
        start = info.data.get("start_minute")
        if start is not None and value <= start:
            raise ValueError("end_minute must be greater than start_minute")
        return value


class CreditConstraintRequest(BaseModel):
    minimum: CreditValue | None = None
    target: CreditValue | None = None
    maximum: CreditValue | None = None
    category_minimums: dict[str, CreditValue] = Field(default_factory=dict, max_length=50)
    category_maximums: dict[str, CreditValue] = Field(default_factory=dict, max_length=50)


class RankingRequest(BaseModel):
    preferred_faculties: list[str] = Field(default_factory=list, max_length=100)
    prefer_morning_theory: bool = False
    prefer_evening_theory: bool = False
    avoid_late_after_minute: int | None = Field(default=None, ge=0, le=1440)
    minimize_labs: bool = True
    minimize_campus_days: bool = True


class ProvisionalPolicyRequest(BaseModel):
    allow_unverified_calendar: bool = False
    allow_user_supplied_metadata: bool = False
    allow_provisional_pairing: bool = False
    allow_unknown_pairing: bool = False
    allow_same_faculty_pairing: bool = False


class ScenarioRequest(BaseModel):
    campus: str = Field(min_length=1, max_length=100)
    semester_label: str = Field(min_length=1, max_length=200)
    calendar_id: str = Field(min_length=1, max_length=200)
    mode: EvaluationMode = EvaluationMode.EXPLORATORY
    courses: list[CourseScenarioRequest] = Field(min_length=1, max_length=100)
    occupied_intervals: list[OccupiedIntervalRequest] = Field(default_factory=list, max_length=200)
    credit_constraints: CreditConstraintRequest = Field(default_factory=CreditConstraintRequest)
    ranking: RankingRequest = Field(default_factory=RankingRequest)
    provisional_policy: ProvisionalPolicyRequest = Field(default_factory=ProvisionalPolicyRequest)
    top_k: int = Field(default=20, ge=1, le=100)
    max_search_nodes: int | None = Field(default=2_000_000, ge=1_000, le=100_000_000)


@router.post("/scenarios/validate")
async def validate_scenario(payload: ScenarioRequest, request: Request) -> dict[str, Any]:
    service: SolverService = request.app.state.solver_service
    validation = service.validate(_scenario_input(payload))
    return {
        "api_version": "1.0",
        "status": "ready" if validation.valid else "unresolved",
        **validation.to_dict(),
    }


@router.post("/jobs", status_code=202, response_model=None)
async def create_job(payload: ScenarioRequest, request: Request) -> dict[str, Any] | JSONResponse:
    service: SolverService = request.app.state.solver_service
    validation = service.validate(_scenario_input(payload))
    if not validation.valid or validation.scenario is None:
        return JSONResponse(
            status_code=422,
            content={
                "api_version": "1.0",
                "status": "unresolved",
                **validation.to_dict(),
            },
        )
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.create(validation.scenario)}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request) -> dict[str, Any]:
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.status(job_id)}


@router.get("/jobs/{job_id}/results")
async def job_results(
    job_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.results(job_id, page=page, page_size=page_size)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.cancel(job_id)}


@router.post("/jobs/{job_id}/count", status_code=202)
async def start_count(job_id: str, request: Request) -> dict[str, Any]:
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.start_count(job_id)}


@router.get("/jobs/{job_id}/count")
async def count_status(job_id: str, request: Request) -> dict[str, Any]:
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.count_status(job_id)}


@router.post("/jobs/{job_id}/count/cancel")
async def cancel_count(job_id: str, request: Request) -> dict[str, Any]:
    jobs: SolverJobManager = request.app.state.solver_jobs
    return {"api_version": "1.0", **jobs.cancel_count(job_id)}


def _scenario_input(payload: ScenarioRequest) -> SolverScenarioInput:
    credits = payload.credit_constraints
    ranking = payload.ranking
    provisional = payload.provisional_policy
    return SolverScenarioInput(
        campus=payload.campus.strip(),
        semester_label=payload.semester_label.strip(),
        calendar_id=payload.calendar_id,
        mode=payload.mode,
        courses=tuple(
            RequestedCourse(
                offering_id=course.offering_id,
                role=course.role,
                curriculum_type=course.curriculum_type,
                curriculum_source=course.curriculum_source,
                credit_milli=_milli(course.credits),
                credit_source=course.credit_source,
                priority_tier=course.priority_tier,
                locked_allocation_ids=tuple(course.locked_allocation_ids),
                locked_faculties=tuple(course.locked_faculties),
                forbidden_allocation_ids=tuple(course.forbidden_allocation_ids),
                forbidden_faculties=tuple(course.forbidden_faculties),
            )
            for course in payload.courses
        ),
        occupied_intervals=tuple(
            RequestedOccupiedInterval(item.day, item.start_minute, item.end_minute, item.label)
            for item in payload.occupied_intervals
        ),
        credit_constraints=CreditConstraints(
            minimum_milli=_milli(credits.minimum),
            target_milli=_milli(credits.target),
            maximum_milli=_milli(credits.maximum),
            category_minimums=tuple(
                sorted(
                    (name, _milli(value) or 0) for name, value in credits.category_minimums.items()
                )
            ),
            category_maximums=tuple(
                sorted(
                    (name, _milli(value) or 0) for name, value in credits.category_maximums.items()
                )
            ),
        ),
        ranking_policy=RankingPolicy(
            preferred_faculties=tuple(ranking.preferred_faculties),
            prefer_morning_theory=ranking.prefer_morning_theory,
            prefer_evening_theory=ranking.prefer_evening_theory,
            avoid_late_after_minute=ranking.avoid_late_after_minute,
            minimize_labs=ranking.minimize_labs,
            minimize_campus_days=ranking.minimize_campus_days,
        ),
        top_k=payload.top_k,
        max_search_nodes=payload.max_search_nodes,
        allow_unverified_calendar=provisional.allow_unverified_calendar,
        allow_user_supplied_metadata=provisional.allow_user_supplied_metadata,
        allow_provisional_pairing=provisional.allow_provisional_pairing,
        allow_unknown_pairing=provisional.allow_unknown_pairing,
        allow_same_faculty_pairing=provisional.allow_same_faculty_pairing,
    )


def _milli(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int(value * 1000)
