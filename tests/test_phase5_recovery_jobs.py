from __future__ import annotations

import multiprocessing
import time
from typing import Any

from ffcs_studio.services.recovery_jobs import RecoveryJobManager


def payload(course_count: int, options_per_course: int) -> dict[str, Any]:
    options = {}
    intended = {}
    must_take = []
    allocation = 1
    for course_index in range(course_count):
        course = f"course-{course_index}"
        must_take.append(course)
        choices = []
        for option_index in range(options_per_course):
            option_id = f"{course}-option-{option_index}"
            choices.append(
                {
                    "option_id": option_id,
                    "allocation_ids": [allocation],
                    "faculty": [f"Synthetic Faculty {option_index}"],
                    "slot_keys": [f"S{option_index}"],
                    "credits_milli": 3000,
                }
            )
            allocation += 1
        intended[course] = choices[0]["option_id"]
        options[course] = choices
    return {
        "intended": intended,
        "options": options,
        "registered_locks": {},
        "must_take": must_take,
        "blocked_allocations": [],
        "priority": {},
        "max_nodes": 100_000_000,
        "top_k": 5,
    }


def wait(manager: RecoveryJobManager, job_id: str) -> dict[str, Any]:
    for _attempt in range(200):
        current = manager.status(job_id)
        if current["status"] not in {"queued", "running", "cancellation_requested"}:
            return current
        time.sleep(0.025)
    raise AssertionError("recovery job did not finish")


def test_process_recovery_job_exact_and_cancelled_shutdown() -> None:
    manager = RecoveryJobManager(max_workers=1, cancel_grace_seconds=0.5)
    try:
        exact = manager.start(payload(2, 2))
        finished = wait(manager, exact["job_id"])
        assert finished["status"] == "exact"
        assert finished["result"]["proven_minimum"] is True

        large = manager.start(payload(12, 6))
        cancelled = manager.cancel(large["job_id"])
        assert cancelled["status"] in {"cancelled", "best_found_so_far"}
        if cancelled["result"] is not None:
            assert cancelled["result"]["proven_minimum"] is False
    finally:
        manager.shutdown()
    assert not [
        child
        for child in multiprocessing.active_children()
        if child.name.startswith("ffcs-recovery-")
    ]
