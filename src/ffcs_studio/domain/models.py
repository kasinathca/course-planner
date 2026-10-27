"""Canonical Phase 0 models with lossless raw source preservation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class KnownComponentType(StrEnum):
    """VTOP allocation row types observed in sanitized evidence."""

    TH = "TH"
    ETH = "ETH"
    ELA = "ELA"
    EPJ = "EPJ"
    SS = "SS"


@dataclass(frozen=True, slots=True)
class CreditBreakdown:
    lecture: int = 0
    tutorial: int = 0
    practical: int = 0
    project: int = 0
    total: int = 0

    def __post_init__(self) -> None:
        if min(self.lecture, self.tutorial, self.practical, self.project, self.total) < 0:
            raise ValueError("credit values cannot be negative")


@dataclass(frozen=True, slots=True)
class CurriculumCourse:
    """A catalogue course, independent of a semester offering."""

    course_id: str
    code: str
    title: str
    category: str
    raw_curriculum_type: str
    credits: CreditBreakdown

    def __post_init__(self) -> None:
        for name in ("course_id", "code", "title", "category", "raw_curriculum_type"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be blank")


@dataclass(frozen=True, slots=True)
class SlotExpression:
    """A preserved raw slot string plus non-semantic atomic tokenization."""

    raw: str
    tokens: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str) -> SlotExpression:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("slot expression cannot be blank")
        tokens = tuple(part.strip() for part in raw.split("+") if part.strip())
        if not tokens:
            raise ValueError("slot expression contains no tokens")
        return cls(raw=raw, tokens=tokens)


@dataclass(frozen=True, slots=True)
class RawVtopAllocationRow:
    """An immutable allocation row exactly as represented by schema v1."""

    source_row: int
    slot: str
    venue: str
    faculty: str
    course_type: str

    def __post_init__(self) -> None:
        if self.source_row < 1:
            raise ValueError("source_row must be at least 1")
        for name in ("slot", "venue", "faculty", "course_type"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} cannot be blank")

    @property
    def known_component_type(self) -> KnownComponentType | None:
        try:
            return KnownComponentType(self.course_type.strip().upper())
        except ValueError:
            return None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RawVtopAllocationRow:
        return cls(
            source_row=value["source_row"],
            slot=value["slot"],
            venue=value["venue"],
            faculty=value["faculty"],
            course_type=value["course_type"],
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "source_row": self.source_row,
            "slot": self.slot,
            "venue": self.venue,
            "faculty": self.faculty,
            "course_type": self.course_type,
        }


@dataclass(frozen=True, slots=True)
class TeachingComponent:
    """A classified view over a preserved raw allocation row."""

    raw_row: RawVtopAllocationRow
    slot_expression: SlotExpression
    known_type: KnownComponentType | None
    needs_review: bool

    @classmethod
    def from_raw_row(cls, row: RawVtopAllocationRow) -> TeachingComponent:
        known = row.known_component_type
        return cls(
            raw_row=row,
            slot_expression=SlotExpression.parse(row.slot),
            known_type=known,
            needs_review=known is None,
        )


@dataclass(frozen=True, slots=True)
class FacultySection:
    """A normalized section view that keeps its source row as provenance."""

    course_code: str
    component: TeachingComponent

    @property
    def raw_faculty_name(self) -> str:
        return self.component.raw_row.faculty

    @property
    def raw_venue(self) -> str:
        return self.component.raw_row.venue


@dataclass(frozen=True, slots=True)
class SemesterOffering:
    """A semester-local offering; no cross-component pairing is inferred."""

    category: str
    course_code: str
    course_title: str
    semester_label: str
    allocations: tuple[RawVtopAllocationRow, ...]

    def __post_init__(self) -> None:
        for name in ("category", "course_code", "course_title", "semester_label"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be blank")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        semester_label: str,
    ) -> SemesterOffering:
        allocations = tuple(RawVtopAllocationRow.from_mapping(row) for row in value["allocations"])
        return cls(
            category=value["category"],
            course_code=value["course_code"],
            course_title=value["course_title"],
            semester_label=semester_label,
            allocations=allocations,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "course_code": self.course_code,
            "course_title": self.course_title,
            "allocations": [row.to_dict() for row in self.allocations],
        }


@dataclass(frozen=True, slots=True)
class ImportSnapshot:
    """A versioned capture envelope retaining all source allocation rows."""

    schema_version: str
    source: str
    campus: str
    semester_label: str
    captured_at: str
    courses: tuple[SemesterOffering, ...]

    def __post_init__(self) -> None:
        for name in ("schema_version", "source", "campus", "semester_label", "captured_at"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be blank")

    @property
    def allocation_count(self) -> int:
        return sum(len(course.allocations) for course in self.courses)

    @property
    def review_components(self) -> tuple[TeachingComponent, ...]:
        components = (
            TeachingComponent.from_raw_row(row)
            for course in self.courses
            for row in course.allocations
        )
        return tuple(component for component in components if component.needs_review)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ImportSnapshot:
        semester_label = value["semester_label"]
        return cls(
            schema_version=value["schema_version"],
            source=value["source"],
            campus=value["campus"],
            semester_label=semester_label,
            captured_at=value["captured_at"],
            courses=tuple(
                SemesterOffering.from_mapping(course, semester_label=semester_label)
                for course in value["courses"]
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "campus": self.campus,
            "semester_label": self.semester_label,
            "captured_at": self.captured_at,
            "courses": [course.to_dict() for course in self.courses],
        }


def duplicate_source_rows(rows: Sequence[RawVtopAllocationRow]) -> tuple[int, ...]:
    """Return repeated ordinals without ever removing their rows."""

    seen: set[int] = set()
    repeated: list[int] = []
    for row in rows:
        if row.source_row in seen:
            repeated.append(row.source_row)
        seen.add(row.source_row)
    return tuple(repeated)
