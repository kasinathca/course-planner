"""Intentionally simple exhaustive oracle for tiny solver scenarios."""

from __future__ import annotations

from ffcs_studio.solver.models import CourseRole, ScenarioSnapshot, SolverCandidate
from ffcs_studio.solver.ranking import build_result
from ffcs_studio.solver.validation import revalidate_assignments


def reference_solution_identities(scenario: ScenarioSnapshot) -> frozenset[str]:
    courses = tuple(course for course in scenario.courses if course.role is not CourseRole.EXCLUDED)
    selected: list[SolverCandidate] = []
    identities: set[str] = set()

    def enumerate_all(index: int) -> None:
        if index == len(courses):
            valid, _reasons = revalidate_assignments(scenario, selected)
            if valid:
                identities.add(build_result(scenario, selected).result_id)
            return
        course = courses[index]
        for candidate in course.candidates:
            selected.append(candidate)
            enumerate_all(index + 1)
            selected.pop()
        if course.role is CourseRole.OPTIONAL:
            enumerate_all(index + 1)

    enumerate_all(0)
    return frozenset(identities)
