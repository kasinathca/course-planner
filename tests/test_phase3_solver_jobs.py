from __future__ import annotations

import time

from ffcs_studio.services.solver_jobs import SolverJobManager
from ffcs_studio.solver.models import (
    CoursePlan,
    CourseRole,
    CreditConstraints,
    CreditSource,
    EvaluationMode,
    RankingPolicy,
    ScenarioSnapshot,
    SolverCandidate,
)


def large_scenario() -> ScenarioSnapshot:
    courses = []
    for course_index in range(20):
        offering_id = course_index + 1
        candidates = tuple(
            SolverCandidate(
                candidate_id=f"C{course_index}-{option}",
                offering_id=offering_id,
                revision_id=1000 + offering_id,
                course_code=f"C{course_index}",
                allocation_ids=(offering_id * 10 + option,),
                meetings=(),
                occupancy_mask=0,
                verification_status="verified",
            )
            for option in range(2)
        )
        courses.append(
            CoursePlan(
                offering_id=offering_id,
                revision_id=1000 + offering_id,
                course_code=f"C{course_index}",
                course_title=f"Course {course_index}",
                category="PE",
                role=CourseRole.REQUIRED if course_index == 0 else CourseRole.OPTIONAL,
                priority_tier=course_index + 1,
                curriculum_type="TH",
                curriculum_source=CreditSource.VERIFIED,
                credit_milli=1000,
                credit_source=CreditSource.VERIFIED,
                candidates=candidates,
            )
        )
    return ScenarioSnapshot(
        scenario_id="cancellation-test",
        fingerprint="c" * 64,
        campus="Vellore",
        semester_label="Synthetic",
        calendar_id="calendar",
        calendar_verification="official_verified",
        mode=EvaluationMode.STRICT_VERIFIED,
        courses=tuple(courses),
        occupied_intervals=(),
        occupied_mask=0,
        credit_constraints=CreditConstraints(),
        ranking_policy=RankingPolicy(),
        top_k=5,
        max_search_nodes=None,
    )


def wait_for_search(manager: SolverJobManager, job_id: str) -> dict[str, object]:
    for _attempt in range(200):
        status = manager.status(job_id)
        if status["status"] not in {"queued", "running", "cancellation_requested"}:
            return status
        time.sleep(0.01)
    raise AssertionError("search worker did not stop")


def wait_for_count(manager: SolverJobManager, job_id: str) -> dict[str, object]:
    for _attempt in range(200):
        status = manager.count_status(job_id)
        if status["status"] not in {"pending", "running"}:
            return status
        time.sleep(0.01)
    raise AssertionError("count worker did not stop")


def test_search_and_count_processes_are_actually_cancellable() -> None:
    manager = SolverJobManager(max_workers=1, cancel_grace_seconds=0.2)
    try:
        created = manager.create(large_scenario())
        job_id = str(created["job_id"])
        manager.cancel(job_id)
        assert wait_for_search(manager, job_id)["status"] == "cancelled"

        manager.start_count(job_id)
        for _attempt in range(100):
            if manager.count_status(job_id)["status"] == "running":
                break
            time.sleep(0.01)
        manager.cancel_count(job_id)
        assert wait_for_count(manager, job_id)["status"] == "cancelled"
    finally:
        manager.shutdown()


def test_worker_concurrency_is_bounded_and_queued() -> None:
    manager = SolverJobManager(max_workers=1, cancel_grace_seconds=0.1)
    try:
        first = manager.create(large_scenario())
        second = manager.create(large_scenario())
        assert first["status"] == "running"
        assert second["status"] == "queued"
        manager.cancel(str(first["job_id"]))
        manager.cancel(str(second["job_id"]))
        assert wait_for_search(manager, str(first["job_id"]))["status"] == "cancelled"
        assert wait_for_search(manager, str(second["job_id"]))["status"] == "cancelled"
    finally:
        manager.shutdown()
