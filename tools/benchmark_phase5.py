"""Reproducible public Phase 5 benchmark using synthetic records only."""

from __future__ import annotations

import statistics
import time

from ffcs_studio.degree.accounting import evaluate_progress
from ffcs_studio.degree.models import (
    PROGRAMME_POLICY_2024,
    CatalogueCourse,
    CourseRecord,
    CourseStatus,
    EvidenceStatus,
    PlanDocument,
)
from ffcs_studio.degree.recovery import RecoveryOption, RecoveryRequest, recover


def measured(action: object, repeats: int = 25) -> tuple[float, float]:
    durations = []
    callable_action = action
    for _attempt in range(repeats):
        started = time.perf_counter()
        callable_action()  # type: ignore[operator]
        durations.append((time.perf_counter() - started) * 1000)
    return statistics.median(durations), max(durations)


def main() -> None:
    courses = {
        f"synthetic-{index}": CatalogueCourse(
            canonical_id=f"synthetic-{index}",
            source_id=f"source-{index}",
            code=f"SYN{index:04d}",
            title=f"Synthetic catalogue course {index}",
            category=("PC", "PE", "UC", "UE", "SPE")[index % 5],
            curriculum_type="TH",
            total_credits_milli=(index % 4 + 1) * 1000,
            provenance=EvidenceStatus.USER_SUPPLIED,
        )
        for index in range(101)
    }
    records = tuple(
        CourseRecord(
            record_id=f"record-{index}",
            course_id=f"synthetic-{index}",
            semester=index % 10 + 1,
            status=(CourseStatus.COMPLETED if index < 35 else CourseStatus.PLANNED),
        )
        for index in range(75)
    )
    document = PlanDocument(
        PROGRAMME_POLICY_2024.programme_code,
        PROGRAMME_POLICY_2024.revision_code,
        records,
    )
    accounting = measured(lambda: evaluate_progress(PROGRAMME_POLICY_2024, courses, document))
    filtering = measured(
        lambda: [course for course in courses.values() if "7" in course.code or "7" in course.title]
    )
    options = {
        f"course-{course}": tuple(
            RecoveryOption(
                course_id=f"course-{course}",
                option_id=f"option-{course}-{choice}",
                allocation_ids=(course * 10 + choice,),
                faculty=(f"Synthetic Faculty {choice}",),
                slot_keys=(f"S{choice}",),
            )
            for choice in range(4)
        )
        for course in range(7)
    }
    recovery_request = RecoveryRequest(
        intended={course: values[0].option_id for course, values in options.items()},
        options=options,
        registered_locks={"course-0": "option-0-0"},
        must_take=frozenset(options),
        blocked_allocations=frozenset({11}),
        priority={},
        max_nodes=50_000,
    )
    recovery = measured(lambda: recover(recovery_request), repeats=5)
    print("Phase 5 synthetic benchmark (median ms / max ms)")
    print(f"101-course, 75-record accounting: {accounting[0]:.3f} / {accounting[1]:.3f}")
    print(f"101-course catalogue filtering: {filtering[0]:.3f} / {filtering[1]:.3f}")
    print(f"7-course, 4-option exact recovery: {recovery[0]:.3f} / {recovery[1]:.3f}")


if __name__ == "__main__":
    main()
