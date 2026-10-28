"""Exact, cancellable counting separate from ranked top-K generation."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ffcs_studio.solver.models import CountOutcome, CountStatus, CourseRole, ScenarioSnapshot
from ffcs_studio.solver.optimized import _ordered_courses, _remaining_credit_bounds

CountProgress = Callable[[dict[str, int | float | str]], None]


def count_exact(
    scenario: ScenarioSnapshot,
    *,
    cancel_event: Any | None = None,
    progress: CountProgress | None = None,
) -> CountOutcome:
    started = time.perf_counter()
    courses = _ordered_courses(scenario)
    remaining_credit = _remaining_credit_bounds(courses)
    categories = tuple(
        sorted(
            {course.category for course in courses}
            | {name for name, _value in scenario.credit_constraints.category_minimums}
            | {name for name, _value in scenario.credit_constraints.category_maximums}
        )
    )
    category_indexes = {name: index for index, name in enumerate(categories)}
    memo: dict[tuple[int, int, int, tuple[int, ...]], int] = {}
    nodes = 0
    pruned = 0
    stopped: CountStatus | None = None

    def should_stop() -> bool:
        nonlocal stopped
        if cancel_event is not None and cancel_event.is_set():
            stopped = CountStatus.CANCELLED
            return True
        if scenario.max_search_nodes is not None and nodes >= scenario.max_search_nodes:
            stopped = CountStatus.RESOURCE_LIMIT
            return True
        return False

    def report(status: str) -> None:
        if progress is not None:
            progress(
                {
                    "status": status,
                    "nodes_visited": nodes,
                    "branches_pruned": pruned,
                    "elapsed_seconds": time.perf_counter() - started,
                }
            )

    def visit(index: int, occupied: int, credits: int, category_values: tuple[int, ...]) -> int:
        nonlocal nodes, pruned
        if should_stop():
            return 0
        key = (index, occupied, credits, category_values)
        if key in memo:
            return memo[key]
        constraints = scenario.credit_constraints
        if constraints.maximum_milli is not None and credits > constraints.maximum_milli:
            pruned += 1
            return 0
        if (
            constraints.minimum_milli is not None
            and credits + remaining_credit[index] < constraints.minimum_milli
        ):
            pruned += 1
            return 0
        if index == len(courses):
            if constraints.minimum_milli is not None and credits < constraints.minimum_milli:
                return 0
            values = dict(zip(categories, category_values, strict=True))
            if any(
                values.get(name, 0) < minimum for name, minimum in constraints.category_minimums
            ):
                return 0
            if any(
                values.get(name, 0) > maximum for name, maximum in constraints.category_maximums
            ):
                return 0
            return 1
        course = courses[index]
        course_credit = course.credit_milli or 0
        next_categories = list(category_values)
        next_categories[category_indexes[course.category]] += course_credit
        included_categories = tuple(next_categories)
        total = 0
        for candidate in course.candidates:
            if should_stop():
                return total
            nodes += 1
            if candidate.occupancy_mask & occupied:
                pruned += 1
                continue
            total += visit(
                index + 1,
                occupied | candidate.occupancy_mask,
                credits + course_credit,
                included_categories,
            )
        if course.role is CourseRole.OPTIONAL and not should_stop():
            nodes += 1
            total += visit(index + 1, occupied, credits, category_values)
        if nodes and nodes % 2048 == 0:
            report("running")
        if stopped is None:
            memo[key] = total
        return total

    exact = visit(0, scenario.occupied_mask, 0, tuple(0 for _item in categories))
    elapsed = time.perf_counter() - started
    status = stopped or CountStatus.EXACT
    report(status.value)
    return CountOutcome(
        status=status,
        exact_count=exact if status is CountStatus.EXACT else None,
        nodes_visited=nodes,
        branches_pruned=pruned,
        elapsed_seconds=elapsed,
        diagnostic=None if status is CountStatus.EXACT else "count did not complete",
    )
