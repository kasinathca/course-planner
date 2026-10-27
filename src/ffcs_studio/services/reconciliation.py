"""Deterministic comparison of proposed partial imports with active offerings."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ffcs_studio.domain.models import RawVtopAllocationRow, SemesterOffering
from ffcs_studio.importers.models import PreparedImport
from ffcs_studio.persistence.repositories import (
    OfferingKey,
    Repository,
    StoredAllocation,
    StoredOffering,
)


@dataclass(frozen=True, slots=True)
class CourseChange:
    course_ordinal: int
    key: OfferingKey
    course_title: str
    change_type: str
    offering_id: int | None
    added_rows: tuple[dict[str, object], ...]
    removed_rows: tuple[dict[str, object], ...]
    modified_rows: tuple[dict[str, object], ...]
    order_changed: bool
    metadata_conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "course_ordinal": self.course_ordinal,
            "campus": self.key.campus,
            "semester_label": self.key.semester_label,
            "category": self.key.category,
            "course_code": self.key.course_code,
            "course_title": self.course_title,
            "change_type": self.change_type,
            "offering_id": self.offering_id,
            "added_rows": list(self.added_rows),
            "removed_rows": list(self.removed_rows),
            "modified_rows": list(self.modified_rows),
            "order_changed": self.order_changed,
            "metadata_conflicts": list(self.metadata_conflicts),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    data_revision: int
    changes: tuple[CourseChange, ...]
    duplicate_import_id: str | None
    warning_count: int

    @property
    def new_courses(self) -> int:
        return sum(change.change_type == "new" for change in self.changes)

    @property
    def updated_courses(self) -> int:
        return sum(change.change_type == "updated" for change in self.changes)

    @property
    def unchanged_courses(self) -> int:
        return sum(change.change_type == "unchanged" for change in self.changes)

    @property
    def added_rows(self) -> int:
        return sum(len(change.added_rows) for change in self.changes)

    @property
    def removed_rows(self) -> int:
        return sum(len(change.removed_rows) for change in self.changes)

    @property
    def modified_rows(self) -> int:
        return sum(len(change.modified_rows) for change in self.changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "data_revision": self.data_revision,
            "duplicate_import_id": self.duplicate_import_id,
            "new_courses": self.new_courses,
            "updated_courses": self.updated_courses,
            "unchanged_courses": self.unchanged_courses,
            "added_rows": self.added_rows,
            "removed_rows": self.removed_rows,
            "modified_rows": self.modified_rows,
            "warning_count": self.warning_count,
            "changes": [change.to_dict() for change in self.changes],
        }


def reconcile(prepared: PreparedImport, repository: Repository) -> ReconciliationReport:
    duplicate = repository.find_import_by_digest(prepared.semantic_sha256)
    changes = tuple(
        _compare_course(
            course_ordinal=index,
            campus=prepared.snapshot.campus,
            incoming=course,
            active=repository.active_offering(
                OfferingKey(
                    campus=prepared.snapshot.campus,
                    semester_label=prepared.snapshot.semester_label,
                    category=course.category,
                    course_code=course.course_code,
                )
            ),
        )
        for index, course in enumerate(prepared.snapshot.courses, start=1)
    )
    return ReconciliationReport(
        data_revision=repository.data_revision(),
        changes=changes,
        duplicate_import_id=str(duplicate["import_id"]) if duplicate else None,
        warning_count=sum(issue.level == "warning" for issue in prepared.issues),
    )


def _compare_course(
    *,
    course_ordinal: int,
    campus: str,
    incoming: SemesterOffering,
    active: StoredOffering | None,
) -> CourseChange:
    key = OfferingKey(
        campus=campus,
        semester_label=incoming.semester_label,
        category=incoming.category,
        course_code=incoming.course_code,
    )
    if active is None:
        return CourseChange(
            course_ordinal=course_ordinal,
            key=key,
            course_title=incoming.course_title,
            change_type="new",
            offering_id=None,
            added_rows=tuple(
                _incoming_dict(row, index) for index, row in enumerate(incoming.allocations, 1)
            ),
            removed_rows=(),
            modified_rows=(),
            order_changed=False,
            metadata_conflicts=(),
        )

    old_signatures = [row.signature for row in active.allocations]
    new_signatures = [_incoming_signature(row) for row in incoming.allocations]
    metadata_conflicts = (
        ("course_title changed",) if active.course_title != incoming.course_title else ()
    )
    if old_signatures == new_signatures and not metadata_conflicts:
        return CourseChange(
            course_ordinal,
            key,
            incoming.course_title,
            "unchanged",
            active.offering_id,
            (),
            (),
            (),
            False,
            (),
        )

    old_counter = Counter(old_signatures)
    new_counter = Counter(new_signatures)
    order_changed = old_counter == new_counter and old_signatures != new_signatures
    modified: list[dict[str, object]] = []
    old_by_source = _unique_stored_by_source(active.allocations)
    new_by_source = _unique_incoming_by_source(incoming.allocations)
    for source_row in sorted(old_by_source.keys() & new_by_source.keys()):
        old_row = old_by_source[source_row]
        new_row = new_by_source[source_row]
        old_signature = old_row.signature
        new_signature = _incoming_signature(new_row[1])
        if old_signature != new_signature:
            modified.append(
                {
                    "source_row": source_row,
                    "before": _stored_dict(old_row),
                    "after": _incoming_dict(new_row[1], new_row[0]),
                }
            )
            old_counter[old_signature] -= 1
            new_counter[new_signature] -= 1

    for signature in old_counter.keys() & new_counter.keys():
        matched = min(old_counter[signature], new_counter[signature])
        old_counter[signature] -= matched
        new_counter[signature] -= matched

    added = _expand_incoming_counter(new_counter, incoming.allocations)
    removed = _expand_stored_counter(old_counter, active.allocations)
    return CourseChange(
        course_ordinal=course_ordinal,
        key=key,
        course_title=incoming.course_title,
        change_type="updated",
        offering_id=active.offering_id,
        added_rows=tuple(added),
        removed_rows=tuple(removed),
        modified_rows=tuple(modified),
        order_changed=order_changed,
        metadata_conflicts=metadata_conflicts,
    )


def _incoming_signature(row: RawVtopAllocationRow) -> tuple[object, ...]:
    return (row.source_row, row.slot, row.venue, row.faculty, row.course_type)


def _incoming_dict(row: RawVtopAllocationRow, ordinal: int) -> dict[str, object]:
    return {
        "allocation_ordinal": ordinal,
        "source_row": row.source_row,
        "slot": row.slot,
        "venue": row.venue,
        "faculty": row.faculty,
        "course_type": row.course_type,
    }


def _stored_dict(row: StoredAllocation) -> dict[str, object]:
    return {
        "allocation_ordinal": row.allocation_ordinal,
        "source_row": row.source_row,
        "slot": row.slot,
        "venue": row.venue,
        "faculty": row.faculty,
        "course_type": row.course_type,
    }


def _unique_stored_by_source(
    rows: tuple[StoredAllocation, ...],
) -> dict[int, StoredAllocation]:
    counts = Counter(row.source_row for row in rows)
    return {row.source_row: row for row in rows if counts[row.source_row] == 1}


def _unique_incoming_by_source(
    rows: tuple[RawVtopAllocationRow, ...],
) -> dict[int, tuple[int, RawVtopAllocationRow]]:
    counts = Counter(row.source_row for row in rows)
    return {
        row.source_row: (ordinal, row)
        for ordinal, row in enumerate(rows, start=1)
        if counts[row.source_row] == 1
    }


def _expand_incoming_counter(
    counter: Counter[tuple[object, ...]],
    rows: tuple[RawVtopAllocationRow, ...],
) -> list[dict[str, object]]:
    remaining = counter.copy()
    result: list[dict[str, object]] = []
    for ordinal, row in enumerate(rows, start=1):
        signature = _incoming_signature(row)
        if remaining[signature] > 0:
            result.append(_incoming_dict(row, ordinal))
            remaining[signature] -= 1
    return result


def _expand_stored_counter(
    counter: Counter[tuple[object, ...]],
    rows: tuple[StoredAllocation, ...],
) -> list[dict[str, object]]:
    remaining = counter.copy()
    result: list[dict[str, object]] = []
    for row in rows:
        if remaining[row.signature] > 0:
            result.append(_stored_dict(row))
            remaining[row.signature] -= 1
    return result
