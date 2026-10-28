"""Privacy-preserving validation of a registered component timetable."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ffcs_studio.domain.calendar import CalendarProfile, SlotResolution, WeeklyInterval
from ffcs_studio.domain.conflicts import ConflictStatus, check_conflicts
from ffcs_studio.domain.workload import Workload, calculate_workload
from ffcs_studio.services.slot_resolution import resolve_slot_expression

UNSCHEDULED_COMPONENT_TYPES = frozenset({"ONLINE", "MOOC"})


@dataclass(frozen=True, slots=True)
class TimetableIssue:
    component_index: int
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TimetableCheck:
    component_count: int
    course_count: int
    total_credits: Decimal
    scheduled_component_count: int
    unscheduled_component_count: int
    interval_count: int
    contact_minutes: int
    workload: Workload
    conflict_pairs: tuple[tuple[int, int], ...]
    issues: tuple[TimetableIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.conflict_pairs and not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "component_count": self.component_count,
            "course_count": self.course_count,
            "total_credits": float(self.total_credits),
            "scheduled_component_count": self.scheduled_component_count,
            "unscheduled_component_count": self.unscheduled_component_count,
            "interval_count": self.interval_count,
            "contact_minutes": self.contact_minutes,
            "meeting_count": self.workload.meeting_count,
            "session_count": self.workload.session_count,
            "conflict_pair_count": len(self.conflict_pairs),
            "issues": [
                {
                    "component_index": issue.component_index,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


def validate_registered_timetable(
    components: Sequence[Mapping[str, object]], calendar: CalendarProfile
) -> TimetableCheck:
    """Resolve every physical component and report only row indexes, never personal fields."""

    issues: list[TimetableIssue] = []
    course_codes: set[str] = set()
    total_credits = Decimal(0)
    scheduled: list[tuple[int, SlotResolution]] = []
    intervals: list[WeeklyInterval] = []
    unscheduled_count = 0

    for index, component in enumerate(components, start=1):
        course_code = str(component.get("course_code", "")).strip()
        if not course_code:
            issues.append(TimetableIssue(index, "missing_course_code", "course_code is required"))
        else:
            course_codes.add(course_code)
        try:
            total_credits += Decimal(str(component.get("credits", "")))
        except InvalidOperation:
            issues.append(TimetableIssue(index, "invalid_credits", "credits must be numeric"))

        slot = str(component.get("slot", "")).strip()
        component_type = str(component.get("component_type", "")).strip().upper()
        if slot.upper() == "NIL":
            if component_type in UNSCHEDULED_COMPONENT_TYPES:
                unscheduled_count += 1
            else:
                issues.append(
                    TimetableIssue(
                        index,
                        "nil_for_scheduled_component",
                        "NIL is unscheduled only for an explicit online/MOOC component",
                    )
                )
            continue
        resolution = resolve_slot_expression(slot, calendar)
        if not resolution.resolved:
            issues.append(
                TimetableIssue(
                    index,
                    "unresolved_slot",
                    "slot expression is malformed or unknown to the selected calendar",
                )
            )
            continue
        scheduled.append((index, resolution))
        intervals.extend(resolution.intervals)

    conflict_pairs: list[tuple[int, int]] = []
    for left_index, (left_row, left) in enumerate(scheduled):
        for right_row, right in scheduled[left_index + 1 :]:
            if check_conflicts(left, right).status is ConflictStatus.CONFIRMED_CLASH:
                conflict_pairs.append((left_row, right_row))

    workload = calculate_workload(intervals)
    return TimetableCheck(
        component_count=len(components),
        course_count=len(course_codes),
        total_credits=total_credits,
        scheduled_component_count=len(scheduled),
        unscheduled_component_count=unscheduled_count,
        interval_count=len(set(intervals)),
        contact_minutes=sum(interval.duration_minutes for interval in intervals),
        workload=workload,
        conflict_pairs=tuple(conflict_pairs),
        issues=tuple(issues),
    )
