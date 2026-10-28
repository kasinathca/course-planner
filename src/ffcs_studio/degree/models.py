"""Typed, HTTP-independent degree-planning models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvidenceStatus(StrEnum):
    OFFICIAL = "official"
    USER_SUPPLIED = "user_supplied"
    LEGACY = "legacy"
    MANUAL = "manual"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class CourseStatus(StrEnum):
    PLANNED = "planned"
    TENTATIVE = "tentative"
    ENROLLED = "enrolled"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"


class RelationshipType(StrEnum):
    EQUIVALENT = "equivalent"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    BASKET = "basket"
    SAME_REQUIREMENT = "same_requirement"
    SAME_CODE_DISTINCT = "same_code_distinct"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class CategoryRequirement:
    code: str
    name: str
    recorded_target_milli: int
    confirmed_credit_target_milli: int | None
    non_credit_target_units: int = 0
    counted_in_graduation: bool | None = True
    surplus_allowed: bool = True
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ProgrammePolicy:
    programme_code: str
    name: str
    admission_batch: str
    revision_code: str
    displayed_total_milli: int
    categories: tuple[CategoryRequirement, ...]
    official_semester_limit_milli: int | None = None
    planning_warning_milli: int | None = 27_000


@dataclass(frozen=True, slots=True)
class CatalogueCourse:
    canonical_id: str
    source_id: str
    code: str
    title: str
    category: str
    curriculum_type: str
    total_credits_milli: int | None
    lecture: int | None = None
    tutorial: int | None = None
    practical: int | None = None
    project: int | None = None
    provenance: EvidenceStatus = EvidenceStatus.UNKNOWN
    alternative_group: str | None = None
    notes: str = ""
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CourseRecord:
    record_id: str
    course_id: str
    semester: int
    status: CourseStatus
    intended_category: str | None = None
    notes: str = ""
    source: EvidenceStatus = EvidenceStatus.MANUAL
    attempt: int = 1
    offering_id: int | None = None


@dataclass(frozen=True, slots=True)
class Relationship:
    relationship_id: str
    relationship_type: RelationshipType
    course_ids: tuple[str, ...]
    requirement_key: str | None
    verified: bool
    provenance: EvidenceStatus
    notes: str = ""


@dataclass(frozen=True, slots=True)
class PrerequisiteRule:
    rule_id: str
    course_id: str
    all_of: tuple[str, ...] = ()
    any_of: tuple[tuple[str, ...], ...] = ()
    minimum_semester: int | None = None
    verified: bool = False
    provenance: EvidenceStatus = EvidenceStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class PlanDocument:
    programme_code: str
    curriculum_revision: str
    records: tuple[CourseRecord, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)


PROGRAMME_POLICY_2024 = ProgrammePolicy(
    programme_code="VIT-IMTECH-CSE-DS",
    name="Integrated M.Tech Computer Science and Engineering (Data Science)",
    admission_batch="2024-25",
    revision_code="2024-25",
    displayed_total_milli=225_000,
    categories=(
        CategoryRequirement("PC", "Programme Core", 81_000, 81_000),
        CategoryRequirement("PE", "Programme Elective", 48_000, 48_000),
        CategoryRequirement("UC", "University Core", 61_000, 61_000),
        CategoryRequirement("UE", "University Elective", 12_000, 12_000),
        CategoryRequirement("SPE", "Specialization Elective", 18_000, 18_000),
        CategoryRequirement("BC", "Bridge Course", 0, 0),
        CategoryRequirement(
            "NC",
            "Non-Credit Course",
            5_000,
            None,
            non_credit_target_units=5,
            counted_in_graduation=None,
            notes=(
                "The source records five units but their ordinary-credit treatment is unresolved."
            ),
        ),
    ),
)
