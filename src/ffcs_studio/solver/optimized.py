"""Deterministic MRV/bitset top-K search with bounded result memory."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ffcs_studio.solver.models import (
    CoursePlan,
    CourseRole,
    ScenarioSnapshot,
    SearchOutcome,
    SearchTermination,
    SolverCandidate,
    TimetableResult,
)
from ffcs_studio.solver.ranking import build_result
from ffcs_studio.solver.validation import credit_constraints_hold, revalidate_assignments

ProgressCallback = Callable[[dict[str, int | float | str]], None]


def solve_top_k(
    scenario: ScenarioSnapshot,
    *,
    cancel_event: Any | None = None,
    progress: ProgressCallback | None = None,
) -> SearchOutcome:
    started = time.perf_counter()
    courses = _ordered_courses(scenario)
    remaining_credit = _remaining_credit_bounds(courses)
    results: list[TimetableResult] = []
    selected: list[SolverCandidate] = []
    nodes = 0
    pruned = 0
    feasible = 0
    stopped: SearchTermination | None = None

    def report(status: str) -> None:
        if progress is not None:
            progress(
                {
                    "status": status,
                    "nodes_visited": nodes,
                    "branches_pruned": pruned,
                    "feasible_solutions_seen": feasible,
                    "elapsed_seconds": time.perf_counter() - started,
                }
            )

    def should_stop() -> bool:
        nonlocal stopped
        if cancel_event is not None and cancel_event.is_set():
            stopped = SearchTermination.CANCELLED
            return True
        if scenario.max_search_nodes is not None and nodes >= scenario.max_search_nodes:
            stopped = SearchTermination.RESOURCE_LIMIT
            return True
        return False

    def visit(index: int, occupied: int, selected_ids: set[int], credits: int) -> None:
        nonlocal nodes, pruned, feasible
        if should_stop():
            return
        constraints = scenario.credit_constraints
        if constraints.maximum_milli is not None and credits > constraints.maximum_milli:
            pruned += 1
            return
        if (
            constraints.minimum_milli is not None
            and credits + remaining_credit[index] < constraints.minimum_milli
        ):
            pruned += 1
            return
        if index == len(courses):
            if not credit_constraints_hold(scenario, selected_ids):
                pruned += 1
                return
            valid, reasons = revalidate_assignments(scenario, selected)
            if not valid:
                raise RuntimeError("optimized solver emitted invalid result: " + "; ".join(reasons))
            feasible += 1
            result = build_result(scenario, selected)
            results.append(result)
            results.sort(key=lambda item: item.ranking_vector)
            del results[scenario.top_k :]
            if feasible <= scenario.top_k or feasible % 256 == 0:
                report("running")
            return

        course = courses[index]
        for candidate in course.candidates:
            if should_stop():
                return
            nodes += 1
            if candidate.occupancy_mask & occupied:
                pruned += 1
                continue
            selected.append(candidate)
            visit(
                index + 1,
                occupied | candidate.occupancy_mask,
                selected_ids | {course.offering_id},
                credits + (course.credit_milli or 0),
            )
            selected.pop()
        if course.role is CourseRole.OPTIONAL and not should_stop():
            nodes += 1
            visit(index + 1, occupied, selected_ids, credits)
        if nodes and nodes % 1024 == 0:
            report("running")

    visit(0, scenario.occupied_mask, set(), 0)
    elapsed = time.perf_counter() - started
    if stopped is None:
        termination = SearchTermination.EXHAUSTED if feasible else SearchTermination.INFEASIBLE
        exhaustive = True
    else:
        termination = stopped
        exhaustive = False
    report(termination.value)
    return SearchOutcome(
        termination=termination,
        exhaustive=exhaustive,
        results=tuple(results),
        feasible_solutions_seen=feasible,
        nodes_visited=nodes,
        branches_pruned=pruned,
        elapsed_seconds=elapsed,
    )


def _ordered_courses(scenario: ScenarioSnapshot) -> tuple[CoursePlan, ...]:
    courses = [course for course in scenario.courses if course.role is not CourseRole.EXCLUDED]
    return tuple(
        sorted(
            courses,
            key=lambda course: (
                0 if course.role is CourseRole.REQUIRED else 1,
                len(course.candidates) + (1 if course.role is CourseRole.OPTIONAL else 0),
                course.priority_tier,
                course.course_code,
                course.offering_id,
            ),
        )
    )


def _remaining_credit_bounds(courses: tuple[CoursePlan, ...]) -> tuple[int, ...]:
    remaining = [0] * (len(courses) + 1)
    for index in range(len(courses) - 1, -1, -1):
        remaining[index] = remaining[index + 1] + (courses[index].credit_milli or 0)
    return tuple(remaining)
