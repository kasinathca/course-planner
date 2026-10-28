"""Immutable typed structures used by reference and optimized solvers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvaluationMode(StrEnum):
    STRICT_VERIFIED = "strict_verified"
    EXPLORATORY = "exploratory"


class CourseRole(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"


class CreditSource(StrEnum):
    VERIFIED = "verified"
    USER_SUPPLIED = "user_supplied"
    UNKNOWN = "unknown"


class SearchTermination(StrEnum):
    EXHAUSTED = "exhausted"
    INFEASIBLE = "infeasible"
    UNRESOLVED = "unresolved"
    CANCELLED = "cancelled"
    RESOURCE_LIMIT = "resource_limit"
    FAILED = "failed"


class CountStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    RUNNING = "running"
    EXACT = "exact"
    CANCELLED = "cancelled"
    RESOURCE_LIMIT = "resource_limit"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, order=True)
class SolverInterval:
    day: int
    start_minute: int
    end_minute: int
    kind: str
    allocation_id: int
    component_type: str
    slot: str
    faculty: str
    venue: str
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.day <= 6:
            raise ValueError("day must be between 0 and 6")
        if not 0 <= self.start_minute < self.end_minute <= 1440:
            raise ValueError("interval must satisfy 0 <= start < end <= 1440")

    @property
    def duration_minutes(self) -> int:
        return self.end_minute - self.start_minute

    def overlaps(self, other: SolverInterval) -> bool:
        return (
            self.day == other.day
            and self.start_minute < other.end_minute
            and other.start_minute < self.end_minute
        )

    def physical_key(self) -> tuple[int, int, int, str, str | None]:
        return (self.day, self.start_minute, self.end_minute, self.kind, self.session_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "day_name": (
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            )[self.day],
            "start_minute": self.start_minute,
            "end_minute": self.end_minute,
            "start_time": _clock(self.start_minute),
            "end_time": _clock(self.end_minute),
            "duration_minutes": self.duration_minutes,
            "kind": self.kind,
            "session_id": self.session_id,
            "allocation_id": self.allocation_id,
            "component_type": self.component_type,
            "slot": self.slot,
            "faculty": self.faculty,
            "venue": self.venue,
        }


@dataclass(frozen=True, slots=True)
class SolverCandidate:
    candidate_id: str
    offering_id: int
    revision_id: int
    course_code: str
    allocation_ids: tuple[int, ...]
    meetings: tuple[SolverInterval, ...]
    occupancy_mask: int
    verification_status: str
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "offering_id": self.offering_id,
            "revision_id": self.revision_id,
            "course_code": self.course_code,
            "allocation_ids": list(self.allocation_ids),
            "verification_status": self.verification_status,
            "assumptions": list(self.assumptions),
            "meetings": [meeting.to_dict() for meeting in self.meetings],
        }


@dataclass(frozen=True, slots=True)
class CoursePlan:
    offering_id: int
    revision_id: int
    course_code: str
    course_title: str
    category: str
    role: CourseRole
    priority_tier: int
    curriculum_type: str
    curriculum_source: CreditSource
    credit_milli: int | None
    credit_source: CreditSource
    candidates: tuple[SolverCandidate, ...]

    def __post_init__(self) -> None:
        if self.priority_tier < 1:
            raise ValueError("priority tier must be at least 1")
        if self.credit_milli is not None and self.credit_milli < 0:
            raise ValueError("course credits cannot be negative")


@dataclass(frozen=True, slots=True)
class CreditConstraints:
    minimum_milli: int | None = None
    target_milli: int | None = None
    maximum_milli: int | None = None
    category_minimums: tuple[tuple[str, int], ...] = ()
    category_maximums: tuple[tuple[str, int], ...] = ()

    @property
    def enabled(self) -> bool:
        return any(
            value is not None
            for value in (self.minimum_milli, self.target_milli, self.maximum_milli)
        ) or bool(self.category_minimums or self.category_maximums)


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    preferred_faculties: tuple[str, ...] = ()
    prefer_morning_theory: bool = False
    prefer_evening_theory: bool = False
    avoid_late_after_minute: int | None = None
    minimize_labs: bool = True
    minimize_campus_days: bool = True


@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    scenario_id: str
    fingerprint: str
    campus: str
    semester_label: str
    calendar_id: str
    calendar_verification: str
    mode: EvaluationMode
    courses: tuple[CoursePlan, ...]
    occupied_intervals: tuple[SolverInterval, ...]
    occupied_mask: int
    credit_constraints: CreditConstraints
    ranking_policy: RankingPolicy
    top_k: int
    max_search_nodes: int | None
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TimetableMetrics:
    total_credits_milli: int | None
    physical_lab_sessions: int
    lab_minutes: int
    total_contact_minutes: int
    campus_days: int
    occupied_span_minutes: int
    interclass_gap_minutes: int
    late_minutes: int
    preferred_faculty_hits: int
    daily_spans: tuple[tuple[int, int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_credits": (
                None if self.total_credits_milli is None else _credit_text(self.total_credits_milli)
            ),
            "physical_lab_sessions": self.physical_lab_sessions,
            "lab_minutes": self.lab_minutes,
            "total_contact_minutes": self.total_contact_minutes,
            "campus_days": self.campus_days,
            "occupied_span_minutes": self.occupied_span_minutes,
            "interclass_gap_minutes": self.interclass_gap_minutes,
            "late_minutes": self.late_minutes,
            "preferred_faculty_hits": self.preferred_faculty_hits,
            "daily_spans": [
                {
                    "day": day,
                    "day_name": (
                        "Monday",
                        "Tuesday",
                        "Wednesday",
                        "Thursday",
                        "Friday",
                        "Saturday",
                        "Sunday",
                    )[day],
                    "start_minute": start,
                    "end_minute": end,
                    "start_time": _clock(start),
                    "end_time": _clock(end),
                }
                for day, start, end in self.daily_spans
            ],
        }


@dataclass(frozen=True, slots=True)
class SelectedCourseMetadata:
    offering_id: int
    revision_id: int
    course_code: str
    course_title: str
    category: str
    credits_milli: int | None
    credit_source: CreditSource
    curriculum_type: str
    curriculum_source: CreditSource

    def to_dict(self) -> dict[str, Any]:
        return {
            "offering_id": self.offering_id,
            "revision_id": self.revision_id,
            "course_code": self.course_code,
            "course_title": self.course_title,
            "category": self.category,
            "credits": (None if self.credits_milli is None else _credit_text(self.credits_milli)),
            "credit_source": self.credit_source.value,
            "curriculum_type": self.curriculum_type,
            "curriculum_source": self.curriculum_source.value,
        }


@dataclass(frozen=True, slots=True)
class TimetableResult:
    result_id: str
    selected_courses: tuple[str, ...]
    course_metadata: tuple[SelectedCourseMetadata, ...]
    assignments: tuple[SolverCandidate, ...]
    metrics: TimetableMetrics
    ranking_vector: tuple[int | str, ...]
    explanation: tuple[str, ...]
    verification_status: str
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "selected_courses": list(self.selected_courses),
            "course_metadata": [item.to_dict() for item in self.course_metadata],
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "metrics": self.metrics.to_dict(),
            "ranking_vector": list(self.ranking_vector),
            "explanation": list(self.explanation),
            "verification_status": self.verification_status,
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    termination: SearchTermination
    exhaustive: bool
    results: tuple[TimetableResult, ...]
    feasible_solutions_seen: int
    nodes_visited: int
    branches_pruned: int
    elapsed_seconds: float
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "termination": self.termination.value,
            "exhaustive": self.exhaustive,
            "results": [result.to_dict() for result in self.results],
            "feasible_solutions_seen": self.feasible_solutions_seen,
            "nodes_visited": self.nodes_visited,
            "branches_pruned": self.branches_pruned,
            "elapsed_seconds": self.elapsed_seconds,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class CountOutcome:
    status: CountStatus
    exact_count: int | None
    nodes_visited: int
    branches_pruned: int
    elapsed_seconds: float
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "exact_count": self.exact_count if self.status is CountStatus.EXACT else None,
            "nodes_visited": self.nodes_visited,
            "branches_pruned": self.branches_pruned,
            "elapsed_seconds": self.elapsed_seconds,
            "diagnostic": self.diagnostic,
        }


def _clock(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def _credit_text(value: int) -> str:
    whole, fraction = divmod(value, 1000)
    return str(whole) if fraction == 0 else f"{whole}.{fraction:03d}".rstrip("0")
