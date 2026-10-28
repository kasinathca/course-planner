"""Scenario validation and immutable solver snapshot construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ffcs_studio.domain.calendar import VerificationStatus
from ffcs_studio.domain.component_rules import CurriculumType
from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.repositories import Repository
from ffcs_studio.solver.candidate_source import (
    CandidateCourseSource,
    CandidatePolicy,
    CompleteCandidateSource,
    source_allocations,
)
from ffcs_studio.solver.models import (
    CoursePlan,
    CourseRole,
    CreditConstraints,
    CreditSource,
    EvaluationMode,
    RankingPolicy,
    ScenarioSnapshot,
    SolverInterval,
)
from ffcs_studio.solver.occupancy import occupancy_mask


@dataclass(frozen=True, slots=True)
class RequestedCourse:
    offering_id: int
    source_revision_id: int | None
    role: CourseRole
    curriculum_type: CurriculumType
    curriculum_source: CreditSource
    credit_milli: int | None
    credit_source: CreditSource
    priority_tier: int = 1
    locked_allocation_ids: tuple[int, ...] = ()
    locked_faculties: tuple[str, ...] = ()
    forbidden_allocation_ids: tuple[int, ...] = ()
    forbidden_faculties: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RequestedOccupiedInterval:
    day: int
    start_minute: int
    end_minute: int
    label: str = "manual commitment"


@dataclass(frozen=True, slots=True)
class SolverScenarioInput:
    campus: str
    semester_label: str
    calendar_id: str
    mode: EvaluationMode
    courses: tuple[RequestedCourse, ...]
    occupied_intervals: tuple[RequestedOccupiedInterval, ...]
    credit_constraints: CreditConstraints
    ranking_policy: RankingPolicy
    top_k: int = 20
    max_search_nodes: int | None = 2_000_000
    allow_unverified_calendar: bool = False
    allow_user_supplied_metadata: bool = False
    allow_provisional_pairing: bool = False
    allow_unknown_pairing: bool = False
    allow_same_faculty_pairing: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioIssue:
    code: str
    message: str
    offering_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "offering_id": self.offering_id,
        }


@dataclass(frozen=True, slots=True)
class ScenarioValidation:
    valid: bool
    issues: tuple[ScenarioIssue, ...]
    assumptions: tuple[str, ...]
    scenario: ScenarioSnapshot | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
            "assumptions": list(self.assumptions),
            "scenario_id": self.scenario.scenario_id if self.scenario else None,
            "scenario_fingerprint": self.scenario.fingerprint if self.scenario else None,
            "course_count": len(self.scenario.courses) if self.scenario else 0,
            "candidate_count": (
                sum(len(course.candidates) for course in self.scenario.courses)
                if self.scenario
                else 0
            ),
        }


class SolverService:
    def __init__(self, repository: Repository, calendars: CalendarRepository) -> None:
        self.repository = repository
        self.calendars = calendars

    def validate(self, request: SolverScenarioInput) -> ScenarioValidation:
        issues: list[ScenarioIssue] = []
        assumptions: list[str] = []
        if not request.courses or all(
            course.role is CourseRole.EXCLUDED for course in request.courses
        ):
            issues.append(
                ScenarioIssue("no_courses", "Select at least one required or optional course")
            )
        if len({course.offering_id for course in request.courses}) != len(request.courses):
            issues.append(ScenarioIssue("duplicate_offering", "An offering may appear only once"))
        if not 1 <= request.top_k <= 100:
            issues.append(ScenarioIssue("invalid_top_k", "top_k must be between 1 and 100"))
        _validate_credit_ranges(request.credit_constraints, issues)

        calendar = self.calendars.get(request.calendar_id)
        if calendar is None:
            issues.append(ScenarioIssue("missing_calendar", "The selected calendar was not found"))
            return ScenarioValidation(False, tuple(issues), (), None)
        if calendar.campus != request.campus or calendar.semester_label != request.semester_label:
            issues.append(
                ScenarioIssue(
                    "calendar_semester_mismatch",
                    "Calendar campus and semester must exactly match the selected offerings",
                )
            )
        if request.mode is EvaluationMode.STRICT_VERIFIED:
            if calendar.verification_status is not VerificationStatus.OFFICIAL_VERIFIED:
                issues.append(
                    ScenarioIssue(
                        "calendar_not_officially_verified",
                        "Strict verified mode requires a reviewed official calendar",
                    )
                )
        elif calendar.verification_status is not VerificationStatus.OFFICIAL_VERIFIED:
            if not request.allow_unverified_calendar:
                issues.append(
                    ScenarioIssue(
                        "unverified_calendar_not_approved",
                        "Exploratory use of this calendar requires explicit approval",
                    )
                )
            else:
                assumptions.append(
                    f"calendar {calendar.calendar_id} is {calendar.verification_status.value}"
                )

        occupied = tuple(
            SolverInterval(
                day=item.day,
                start_minute=item.start_minute,
                end_minute=item.end_minute,
                kind="other",
                allocation_id=-(index + 1),
                component_type="OCCUPIED",
                slot=item.label,
                faculty="",
                venue="",
            )
            for index, item in enumerate(request.occupied_intervals)
        )
        policy = CandidatePolicy(
            allow_provisional_pairing=request.allow_provisional_pairing,
            allow_unknown_pairing=request.allow_unknown_pairing,
            allow_same_faculty_pairing=request.allow_same_faculty_pairing,
        )
        plans: list[CoursePlan] = []
        seen_course_codes: set[str] = set()
        for requested in request.courses:
            detail = self.repository.offering_detail(requested.offering_id)
            allocations = self.repository.offering_allocations(requested.offering_id)
            if detail is None or allocations is None:
                issues.append(
                    ScenarioIssue(
                        "offering_not_found",
                        "The selected offering was not found",
                        requested.offering_id,
                    )
                )
                continue
            if (
                detail["campus"] != request.campus
                or detail["semester_label"] != request.semester_label
            ):
                issues.append(
                    ScenarioIssue(
                        "offering_semester_mismatch",
                        "Every offering must match the scenario campus and semester",
                        requested.offering_id,
                    )
                )
                continue
            course_code = str(detail["course_code"])
            if requested.role is not CourseRole.EXCLUDED and course_code in seen_course_codes:
                issues.append(
                    ScenarioIssue(
                        "duplicate_course",
                        "The same course code cannot be selected twice",
                        requested.offering_id,
                    )
                )
            seen_course_codes.add(course_code)
            if requested.role is CourseRole.EXCLUDED:
                plans.append(
                    CoursePlan(
                        requested.offering_id,
                        int(str(detail["revision_id"])),
                        course_code,
                        str(detail["course_title"]),
                        str(detail["category"]),
                        requested.role,
                        requested.priority_tier,
                        requested.curriculum_type.value,
                        requested.curriculum_source,
                        requested.credit_milli,
                        requested.credit_source,
                        (),
                    )
                )
                continue
            self._validate_metadata(request, requested, issues, assumptions)
            revision_id = int(str(detail["revision_id"]))
            if (
                requested.source_revision_id is not None
                and requested.source_revision_id != revision_id
            ):
                issues.append(
                    ScenarioIssue(
                        "offering_revision_mismatch",
                        "The saved offering revision is no longer active; review and relink "
                        "it explicitly",
                        requested.offering_id,
                    )
                )
            candidate_source = CompleteCandidateSource(
                CandidateCourseSource(
                    offering_id=requested.offering_id,
                    revision_id=revision_id,
                    course_code=course_code,
                    curriculum_type=requested.curriculum_type,
                    curriculum_verified=requested.curriculum_source is CreditSource.VERIFIED,
                    allocations=source_allocations(allocations),
                    pairing_states=self.calendars.pairing_states(revision_id),
                ),
                calendar,
                policy,
            )
            candidates = tuple(candidate_source)
            allocation_faculties = {
                int(str(item["allocation_id"])): _faculty_key(str(item["faculty"]))
                for item in allocations
            }
            locked = set(requested.locked_allocation_ids)
            locked_faculties = {_faculty_key(item) for item in requested.locked_faculties}
            forbidden = set(requested.forbidden_allocation_ids)
            forbidden_faculties = {_faculty_key(item) for item in requested.forbidden_faculties}
            candidates = tuple(
                candidate
                for candidate in candidates
                if locked <= set(candidate.allocation_ids)
                and locked_faculties
                <= {
                    allocation_faculties.get(allocation_id, "")
                    for allocation_id in candidate.allocation_ids
                }
                and not forbidden.intersection(candidate.allocation_ids)
                and not any(
                    allocation_faculties.get(allocation_id) in forbidden_faculties
                    for allocation_id in candidate.allocation_ids
                )
                and not candidate.occupancy_mask & occupancy_mask(occupied)
            )
            if not candidates:
                diagnostic = candidate_source.diagnostics()
                message = (
                    diagnostic[0]
                    if diagnostic
                    else (
                        "No complete option resolves against the selected calendar and "
                        "hard restrictions"
                    )
                )
                issues.append(
                    ScenarioIssue("no_complete_registration_option", message, requested.offering_id)
                )
            assumptions.extend(item for candidate in candidates for item in candidate.assumptions)
            plans.append(
                CoursePlan(
                    offering_id=requested.offering_id,
                    revision_id=revision_id,
                    course_code=course_code,
                    course_title=str(detail["course_title"]),
                    category=str(detail["category"]),
                    role=requested.role,
                    priority_tier=requested.priority_tier,
                    curriculum_type=requested.curriculum_type.value,
                    curriculum_source=requested.curriculum_source,
                    credit_milli=requested.credit_milli,
                    credit_source=requested.credit_source,
                    candidates=candidates,
                )
            )

        if issues:
            return ScenarioValidation(False, tuple(issues), tuple(dict.fromkeys(assumptions)), None)
        assumptions_tuple = tuple(dict.fromkeys(assumptions))
        fingerprint = _fingerprint(request, calendar.calendar_id, plans, assumptions_tuple)
        scenario = ScenarioSnapshot(
            scenario_id=f"scenario-{fingerprint[:16]}",
            fingerprint=fingerprint,
            campus=request.campus,
            semester_label=request.semester_label,
            calendar_id=calendar.calendar_id,
            calendar_verification=calendar.verification_status.value,
            mode=request.mode,
            courses=tuple(plans),
            occupied_intervals=occupied,
            occupied_mask=occupancy_mask(occupied),
            credit_constraints=request.credit_constraints,
            ranking_policy=request.ranking_policy,
            top_k=request.top_k,
            max_search_nodes=request.max_search_nodes,
            assumptions=assumptions_tuple,
        )
        return ScenarioValidation(True, (), assumptions_tuple, scenario)

    def _validate_metadata(
        self,
        scenario: SolverScenarioInput,
        course: RequestedCourse,
        issues: list[ScenarioIssue],
        assumptions: list[str],
    ) -> None:
        if course.curriculum_type is CurriculumType.UNKNOWN:
            issues.append(
                ScenarioIssue(
                    "missing_curriculum_type",
                    "A reviewed curriculum type is required",
                    course.offering_id,
                )
            )
        elif scenario.mode is EvaluationMode.STRICT_VERIFIED:
            if course.curriculum_source is not CreditSource.VERIFIED:
                issues.append(
                    ScenarioIssue(
                        "curriculum_metadata_not_verified",
                        "Strict mode requires verified curriculum component metadata",
                        course.offering_id,
                    )
                )
        elif course.curriculum_source is not CreditSource.VERIFIED:
            if not scenario.allow_user_supplied_metadata:
                issues.append(
                    ScenarioIssue(
                        "user_metadata_not_approved",
                        "Exploratory user-supplied curriculum metadata requires approval",
                        course.offering_id,
                    )
                )
            else:
                assumptions.append(
                    f"offering {course.offering_id} uses user-supplied curriculum metadata"
                )
        if scenario.credit_constraints.enabled:
            if course.credit_milli is None or course.credit_source is CreditSource.UNKNOWN:
                issues.append(
                    ScenarioIssue(
                        "missing_credit_metadata",
                        "Credit constraints require an explicit credit value and source",
                        course.offering_id,
                    )
                )
            elif scenario.mode is EvaluationMode.STRICT_VERIFIED:
                if course.credit_source is not CreditSource.VERIFIED:
                    issues.append(
                        ScenarioIssue(
                            "credit_metadata_not_verified",
                            "Strict credit planning requires verified credit metadata",
                            course.offering_id,
                        )
                    )
            elif course.credit_source is CreditSource.USER_SUPPLIED:
                if scenario.allow_user_supplied_metadata:
                    assumptions.append(f"offering {course.offering_id} uses user-supplied credits")
                else:
                    issues.append(
                        ScenarioIssue(
                            "user_credit_not_approved",
                            "Exploratory user-supplied credits require approval",
                            course.offering_id,
                        )
                    )


def _validate_credit_ranges(
    constraints: CreditConstraints,
    issues: list[ScenarioIssue],
) -> None:
    values = [
        value
        for value in (
            constraints.minimum_milli,
            constraints.target_milli,
            constraints.maximum_milli,
        )
        if value is not None
    ]
    if any(value < 0 for value in values):
        issues.append(ScenarioIssue("invalid_credit_constraint", "Credits cannot be negative"))
    if (
        constraints.minimum_milli is not None
        and constraints.maximum_milli is not None
        and constraints.minimum_milli > constraints.maximum_milli
    ):
        issues.append(
            ScenarioIssue("invalid_credit_constraint", "Minimum credits exceed maximum credits")
        )
    if constraints.target_milli is not None and (
        (
            constraints.minimum_milli is not None
            and constraints.target_milli < constraints.minimum_milli
        )
        or (
            constraints.maximum_milli is not None
            and constraints.target_milli > constraints.maximum_milli
        )
    ):
        issues.append(
            ScenarioIssue("invalid_credit_constraint", "Target credits must be within the range")
        )


def _fingerprint(
    request: SolverScenarioInput,
    calendar_id: str,
    plans: list[CoursePlan],
    assumptions: tuple[str, ...],
) -> str:
    requested_by_id = {course.offering_id: course for course in request.courses}
    payload = {
        "campus": request.campus,
        "semester": request.semester_label,
        "calendar_id": calendar_id,
        "mode": request.mode.value,
        "courses": [
            {
                "offering_id": course.offering_id,
                "revision_id": course.revision_id,
                "role": course.role.value,
                "priority": course.priority_tier,
                "credits": course.credit_milli,
                "credit_source": course.credit_source.value,
                "curriculum": course.curriculum_type,
                "curriculum_source": course.curriculum_source.value,
                "locked_allocation_ids": requested_by_id[course.offering_id].locked_allocation_ids,
                "locked_faculties": requested_by_id[course.offering_id].locked_faculties,
                "forbidden_allocation_ids": (
                    requested_by_id[course.offering_id].forbidden_allocation_ids
                ),
                "forbidden_faculties": requested_by_id[course.offering_id].forbidden_faculties,
                "candidates": [candidate.candidate_id for candidate in course.candidates],
            }
            for course in plans
        ],
        "occupied": [
            (item.day, item.start_minute, item.end_minute) for item in request.occupied_intervals
        ],
        "credits": {
            "minimum": request.credit_constraints.minimum_milli,
            "target": request.credit_constraints.target_milli,
            "maximum": request.credit_constraints.maximum_milli,
            "category_minimums": request.credit_constraints.category_minimums,
            "category_maximums": request.credit_constraints.category_maximums,
        },
        "ranking": {
            "preferred_faculties": request.ranking_policy.preferred_faculties,
            "morning": request.ranking_policy.prefer_morning_theory,
            "evening": request.ranking_policy.prefer_evening_theory,
            "late": request.ranking_policy.avoid_late_after_minute,
            "labs": request.ranking_policy.minimize_labs,
            "days": request.ranking_policy.minimize_campus_days,
        },
        "top_k": request.top_k,
        "max_search_nodes": request.max_search_nodes,
        "pairing_policy": {
            "allow_unverified_calendar": request.allow_unverified_calendar,
            "allow_user_supplied_metadata": request.allow_user_supplied_metadata,
            "allow_provisional_pairing": request.allow_provisional_pairing,
            "allow_unknown_pairing": request.allow_unknown_pairing,
            "allow_same_faculty_pairing": request.allow_same_faculty_pairing,
        },
        "assumptions": assumptions,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _faculty_key(value: str) -> str:
    return " ".join(value.casefold().split())
