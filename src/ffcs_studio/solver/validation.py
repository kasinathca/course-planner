"""Independent hard-constraint validation for complete solver assignments."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ffcs_studio.solver.models import (
    CoursePlan,
    CourseRole,
    ScenarioSnapshot,
    SolverCandidate,
    SolverInterval,
)


def credits_for(
    courses: Sequence[CoursePlan], selected_offering_ids: set[int]
) -> tuple[int | None, Counter[str]]:
    total = 0
    categories: Counter[str] = Counter()
    for course in courses:
        if course.offering_id not in selected_offering_ids:
            continue
        if course.credit_milli is None:
            return None, categories
        total += course.credit_milli
        categories[course.category] += course.credit_milli
    return total, categories


def credit_constraints_hold(
    scenario: ScenarioSnapshot,
    selected_offering_ids: set[int],
) -> bool:
    total, categories = credits_for(scenario.courses, selected_offering_ids)
    constraints = scenario.credit_constraints
    if constraints.enabled and total is None:
        return False
    if total is not None:
        if constraints.minimum_milli is not None and total < constraints.minimum_milli:
            return False
        if constraints.maximum_milli is not None and total > constraints.maximum_milli:
            return False
    if any(categories[category] < minimum for category, minimum in constraints.category_minimums):
        return False
    return not any(
        categories[category] > maximum for category, maximum in constraints.category_maximums
    )


def revalidate_assignments(
    scenario: ScenarioSnapshot,
    assignments: Sequence[SolverCandidate],
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    by_offering = {assignment.offering_id: assignment for assignment in assignments}
    if len(by_offering) != len(assignments):
        reasons.append("a course was assigned more than once")
    required = {
        course.offering_id for course in scenario.courses if course.role is CourseRole.REQUIRED
    }
    excluded = {
        course.offering_id for course in scenario.courses if course.role is CourseRole.EXCLUDED
    }
    if not required <= set(by_offering):
        reasons.append("a required course is missing")
    if excluded & set(by_offering):
        reasons.append("an excluded course is present")
    occupied = scenario.occupied_mask
    all_meetings: list[SolverInterval] = []
    for assignment in assignments:
        if occupied & assignment.occupancy_mask:
            reasons.append(f"{assignment.course_code} conflicts with an occupied period")
        occupied |= assignment.occupancy_mask
        all_meetings.extend(assignment.meetings)
    for index, left in enumerate(all_meetings):
        for right in all_meetings[index + 1 :]:
            if left.allocation_id != right.allocation_id and left.overlaps(right):
                reasons.append("selected course meetings overlap")
                break
        if reasons and reasons[-1] == "selected course meetings overlap":
            break
    if not credit_constraints_hold(scenario, set(by_offering)):
        reasons.append("credit or category constraints are not satisfied")
    return not reasons, tuple(reasons)
