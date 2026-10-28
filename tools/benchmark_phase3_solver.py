"""Reproducible public Phase 3 solver benchmark using the Fall 2026-27 calendar."""

from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import platform
import sys
import tempfile
import time
import tracemalloc
from importlib import resources
from pathlib import Path
from typing import Any

from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.database import Database
from ffcs_studio.services.calendar_service import CalendarService
from ffcs_studio.services.slot_resolution import resolve_slot_expression
from ffcs_studio.services.solver_jobs import SolverJobManager
from ffcs_studio.solver.counting import count_exact
from ffcs_studio.solver.models import (
    CoursePlan,
    CourseRole,
    CreditConstraints,
    CreditSource,
    EvaluationMode,
    RankingPolicy,
    ScenarioSnapshot,
    SolverCandidate,
    SolverInterval,
)
from ffcs_studio.solver.occupancy import occupancy_mask
from ffcs_studio.solver.optimized import solve_top_k

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "examples" / "fall_2026-27_weekday_slot_calendar_USER_SUPPLIED.json"


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    ]


def main() -> None:
    calendar = load_calendar()
    independent = independent_slot_candidates(calendar)
    if len(independent) < 15:
        raise RuntimeError(
            f"benchmark requires 15 independent Fall slots; found {len(independent)}"
        )

    exact_scenario = scenario(8, independent[:8], max_nodes=None)
    first_result: float | None = None
    first_twenty: float | None = None
    started = time.perf_counter()

    def progress(value: dict[str, int | float | str]) -> None:
        nonlocal first_result, first_twenty
        feasible = int(value.get("feasible_solutions_seen", 0))
        elapsed = time.perf_counter() - started
        if feasible >= 1 and first_result is None:
            first_result = elapsed
        if feasible >= 20 and first_twenty is None:
            first_twenty = elapsed

    tracemalloc.start()
    search = solve_top_k(exact_scenario, progress=progress)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    count_started = time.perf_counter()
    counted = count_exact(exact_scenario)
    count_elapsed = time.perf_counter() - count_started

    cancellation = cancellation_study(scenario(15, independent[:15], max_nodes=None))
    memory = memory_status()
    report = {
        "environment": {
            "windows": platform.platform(),
            "python": sys.version.split()[0],
            "cpu": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
            "logical_processors": os.cpu_count(),
            "available_memory_bytes": memory.available_physical,
            "total_memory_bytes": memory.total_physical,
        },
        "calendar": {
            "path": str(CALENDAR_PATH.relative_to(ROOT)),
            "calendar_id": calendar.calendar_id,
            "verification_status": calendar.verification_status.value,
            "atomic_slots": len(calendar.slots),
            "independent_slots_used": [item.candidate_id for item in independent[:15]],
        },
        "exact_eight_course_scenario": {
            "selected_courses": len(exact_scenario.courses),
            "available_section_candidates": sum(
                len(course.candidates) for course in exact_scenario.courses
            ),
            "theoretical_unpruned_assignments": 8**8,
            "termination": search.termination.value,
            "nodes_visited": search.nodes_visited,
            "branches_pruned": search.branches_pruned,
            "feasible_solutions_seen": search.feasible_solutions_seen,
            "top_k_retained": len(search.results),
            "search_seconds": search.elapsed_seconds,
            "time_to_first_result_seconds": first_result,
            "time_to_first_20_results_seconds": first_twenty,
            "peak_tracemalloc_bytes": peak,
            "exact_count_status": counted.status.value,
            "exact_count": counted.exact_count,
            "exact_count_nodes": counted.nodes_visited,
            "exact_count_branches_pruned": counted.branches_pruned,
            "exact_count_seconds": count_elapsed,
        },
        "fifteen_course_cancellation": cancellation,
    }
    print(json.dumps(report, indent=2))


def load_calendar() -> Any:
    with tempfile.TemporaryDirectory(prefix="ffcs-phase3-benchmark-") as directory:
        database = Database(Path(directory) / "benchmark.sqlite3")
        database.initialize()
        repository = CalendarRepository(database)
        schema = json.loads(
            resources.files("ffcs_studio.resources.schemas")
            .joinpath("slot-calendar.schema.json")
            .read_text(encoding="utf-8")
        )
        service = CalendarService(repository, schema)
        validated = service.validate(json.loads(CALENDAR_PATH.read_text(encoding="utf-8")))
        preview = service.preview(validated["validation_id"])
        committed = service.commit(preview["preview_id"], make_active=True)
        calendar = repository.get(committed["calendar_id"])
        if calendar is None:
            raise RuntimeError("calendar commit did not produce a readable profile")
        return calendar


def independent_slot_candidates(calendar: Any) -> tuple[SolverCandidate, ...]:
    selected: list[SolverCandidate] = []
    occupied = 0
    for code in sorted(calendar.slots):
        resolution = resolve_slot_expression(code, calendar)
        if not resolution.resolved:
            continue
        intervals = tuple(
            SolverInterval(
                day=int(interval.day),
                start_minute=interval.start_minute,
                end_minute=interval.end_minute,
                kind=interval.kind.value,
                allocation_id=index + 1,
                component_type="ELA" if interval.kind.value == "lab" else "TH",
                slot=code,
                faculty=f"Benchmark Faculty {index + 1}",
                venue=f"Benchmark Venue {index + 1}",
                session_id=interval.session_id,
            )
            for index, interval in enumerate(resolution.intervals)
        )
        mask = occupancy_mask(intervals)
        if mask & occupied:
            continue
        candidate = SolverCandidate(
            candidate_id=code,
            offering_id=0,
            revision_id=0,
            course_code="",
            allocation_ids=(len(selected) + 1,),
            meetings=intervals,
            occupancy_mask=mask,
            verification_status="exploratory",
            assumptions=("uses the user-supplied Fall calendar",),
        )
        selected.append(candidate)
        occupied |= mask
    return tuple(selected)


def scenario(
    course_count: int,
    slots: tuple[SolverCandidate, ...],
    *,
    max_nodes: int | None,
) -> ScenarioSnapshot:
    courses = []
    for course_index in range(course_count):
        offering_id = course_index + 1
        code = f"SYN{offering_id:02d}"
        candidates = tuple(
            SolverCandidate(
                candidate_id=f"{code}:{slot.candidate_id}",
                offering_id=offering_id,
                revision_id=1000 + offering_id,
                course_code=code,
                allocation_ids=(slot_index + 1,),
                meetings=tuple(
                    SolverInterval(
                        day=item.day,
                        start_minute=item.start_minute,
                        end_minute=item.end_minute,
                        kind=item.kind,
                        allocation_id=offering_id * 100 + slot_index,
                        component_type=item.component_type,
                        slot=item.slot,
                        faculty=item.faculty,
                        venue=item.venue,
                        session_id=item.session_id,
                    )
                    for item in slot.meetings
                ),
                occupancy_mask=slot.occupancy_mask,
                verification_status="exploratory",
                assumptions=slot.assumptions,
            )
            for slot_index, slot in enumerate(slots, start=1)
        )
        courses.append(
            CoursePlan(
                offering_id=offering_id,
                revision_id=1000 + offering_id,
                course_code=code,
                course_title=f"Synthetic benchmark course {offering_id}",
                category="BENCHMARK",
                role=CourseRole.REQUIRED,
                priority_tier=1,
                curriculum_type="TH",
                curriculum_source=CreditSource.USER_SUPPLIED,
                credit_milli=3000,
                credit_source=CreditSource.USER_SUPPLIED,
                candidates=candidates,
            )
        )
    return ScenarioSnapshot(
        scenario_id=f"benchmark-{course_count}",
        fingerprint=f"benchmark-{course_count}-fall-user-supplied",
        campus="Vellore",
        semester_label="Fall Semester 2026-27",
        calendar_id="fall-user-supplied",
        calendar_verification="user_supplied",
        mode=EvaluationMode.EXPLORATORY,
        courses=tuple(courses),
        occupied_intervals=(),
        occupied_mask=0,
        credit_constraints=CreditConstraints(),
        ranking_policy=RankingPolicy(),
        top_k=20,
        max_search_nodes=max_nodes,
        assumptions=("public synthetic courses over user-supplied Fall calendar intervals",),
    )


def cancellation_study(scenario_value: ScenarioSnapshot) -> dict[str, Any]:
    manager = SolverJobManager(max_workers=1, cancel_grace_seconds=0.5)
    created = manager.create(scenario_value)
    job_id = str(created["job_id"])
    deadline = time.perf_counter() + 10
    status = created
    while time.perf_counter() < deadline:
        status = manager.status(job_id)
        if int(status["progress"].get("nodes_visited", 0)) >= 1_000:
            break
        time.sleep(0.01)
    cancel_started = time.perf_counter()
    manager.cancel(job_id)
    while time.perf_counter() < deadline:
        status = manager.status(job_id)
        if status["status"] not in {"queued", "running", "cancellation_requested"}:
            break
        time.sleep(0.005)
    latency = time.perf_counter() - cancel_started
    manager.shutdown()
    time.sleep(0.05)
    remaining = [
        child.name for child in multiprocessing.active_children() if child.name.startswith("ffcs-")
    ]
    return {
        "selected_courses": len(scenario_value.courses),
        "available_section_candidates": sum(
            len(course.candidates) for course in scenario_value.courses
        ),
        "status": status["status"],
        "nodes_before_or_at_cancel": status["progress"].get("nodes_visited", 0),
        "cancellation_latency_seconds": latency,
        "worker_processes_remaining_after_shutdown": remaining,
    }


def memory_status() -> MemoryStatus:
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return status


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
