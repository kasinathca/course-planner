"""Deterministic lexicographic timetable ranking and explanations."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence

from ffcs_studio.solver.models import (
    EvaluationMode,
    ScenarioSnapshot,
    SelectedCourseMetadata,
    SolverCandidate,
    SolverInterval,
    TimetableMetrics,
    TimetableResult,
)
from ffcs_studio.solver.validation import credits_for


def build_result(
    scenario: ScenarioSnapshot,
    assignments: Sequence[SolverCandidate],
) -> TimetableResult:
    ordered = tuple(sorted(assignments, key=lambda item: (item.course_code, item.candidate_id)))
    selected_ids = {item.offering_id for item in ordered}
    course_by_id = {course.offering_id: course for course in scenario.courses}
    selected_courses = tuple(sorted(course_by_id[item].course_code for item in selected_ids))
    course_metadata = tuple(
        SelectedCourseMetadata(
            offering_id=course.offering_id,
            revision_id=course.revision_id,
            course_code=course.course_code,
            course_title=course.course_title,
            category=course.category,
            credits_milli=course.credit_milli,
            credit_source=course.credit_source,
            curriculum_type=course.curriculum_type,
            curriculum_source=course.curriculum_source,
        )
        for course in sorted(
            (course_by_id[item] for item in selected_ids),
            key=lambda item: (item.course_code, item.offering_id),
        )
    )
    meetings = tuple(meeting for assignment in ordered for meeting in assignment.meetings)
    total_credits, _categories = credits_for(scenario.courses, selected_ids)
    metrics = _metrics(scenario, meetings, total_credits)
    tiers = sorted(
        {course.priority_tier for course in scenario.courses if course.role.value == "optional"}
    )
    tier_counts = tuple(
        -sum(
            1
            for course in scenario.courses
            if course.offering_id in selected_ids
            and course.role.value == "optional"
            and course.priority_tier == tier
        )
        for tier in tiers
    )
    target = scenario.credit_constraints.target_milli
    target_distance = 0 if target is None or total_credits is None else abs(total_credits - target)
    time_preference_penalty = _time_preference_penalty(scenario, meetings)
    stable_assignment_key = ",".join(item.candidate_id for item in ordered)
    vector: tuple[int | str, ...] = (
        *tier_counts,
        target_distance,
        metrics.physical_lab_sessions if scenario.ranking_policy.minimize_labs else 0,
        metrics.lab_minutes if scenario.ranking_policy.minimize_labs else 0,
        metrics.campus_days if scenario.ranking_policy.minimize_campus_days else 0,
        metrics.occupied_span_minutes,
        metrics.interclass_gap_minutes,
        time_preference_penalty,
        -metrics.preferred_faculty_hits,
        stable_assignment_key,
    )
    revision_key = ",".join(f"{item.revision_id}:{item.candidate_id}" for item in ordered)
    identity = f"{scenario.calendar_id}:{revision_key}"
    result_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    assumptions = tuple(
        dict.fromkeys(
            (
                *scenario.assumptions,
                *(item for candidate in ordered for item in candidate.assumptions),
            )
        )
    )
    verified = (
        scenario.mode is EvaluationMode.STRICT_VERIFIED
        and not assumptions
        and all(item.verification_status == "verified" for item in ordered)
    )
    explanation = (
        f"Includes {len(selected_courses)} course(s) under all configured hard constraints.",
        f"Uses {metrics.physical_lab_sessions} physical lab session(s) and "
        f"{metrics.lab_minutes} lab minute(s) per week.",
        f"Requires {metrics.campus_days} campus day(s), with "
        f"{metrics.interclass_gap_minutes} interclass gap minute(s).",
        "Optional-course priority tiers are compared before workload preferences.",
    )
    return TimetableResult(
        result_id=result_id,
        selected_courses=selected_courses,
        course_metadata=course_metadata,
        assignments=ordered,
        metrics=metrics,
        ranking_vector=vector,
        explanation=explanation,
        verification_status="verified" if verified else "exploratory",
        assumptions=assumptions,
    )


def _metrics(
    scenario: ScenarioSnapshot,
    meetings: Sequence[SolverInterval],
    total_credits: int | None,
) -> TimetableMetrics:
    unique = tuple(
        {
            (
                item.day,
                item.start_minute,
                item.end_minute,
                item.kind,
                item.session_id,
                item.allocation_id,
            ): item
            for item in meetings
        }.values()
    )
    merged_by_day: dict[int, list[tuple[int, int]]] = defaultdict(list)
    lab_by_day: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for meeting in unique:
        merged_by_day[meeting.day].append((meeting.start_minute, meeting.end_minute))
        if meeting.kind == "lab":
            lab_by_day[meeting.day].append((meeting.start_minute, meeting.end_minute))
    merged = {day: _merge(values) for day, values in merged_by_day.items()}
    lab_merged = {day: _merge(values) for day, values in lab_by_day.items()}
    contact = sum(end - start for values in merged.values() for start, end in values)
    lab_minutes = sum(end - start for values in lab_merged.values() for start, end in values)
    spans = sum(values[-1][1] - values[0][0] for values in merged.values() if values)
    gaps = spans - contact
    session_keys = {
        (item.day, item.session_id)
        if item.session_id
        else (item.day, f"allocation-{item.allocation_id}")
        for item in unique
        if item.kind == "lab"
    }
    cutoff = scenario.ranking_policy.avoid_late_after_minute
    late_minutes = 0
    if cutoff is not None:
        late_minutes = sum(
            max(0, end - max(start, cutoff)) for values in merged.values() for start, end in values
        )
    preferred = {
        " ".join(value.casefold().split()) for value in scenario.ranking_policy.preferred_faculties
    }
    faculty_hits = len(
        {
            (item.allocation_id, " ".join(item.faculty.casefold().split()))
            for item in unique
            if " ".join(item.faculty.casefold().split()) in preferred
        }
    )
    return TimetableMetrics(
        total_credits_milli=total_credits,
        physical_lab_sessions=len(session_keys),
        lab_minutes=lab_minutes,
        total_contact_minutes=contact,
        campus_days=len(merged),
        occupied_span_minutes=spans,
        interclass_gap_minutes=gaps,
        late_minutes=late_minutes,
        preferred_faculty_hits=faculty_hits,
        daily_spans=tuple(
            (day, values[0][0], values[-1][1]) for day, values in sorted(merged.items()) if values
        ),
    )


def _merge(values: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(set(values)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _time_preference_penalty(
    scenario: ScenarioSnapshot,
    meetings: Sequence[SolverInterval],
) -> int:
    policy = scenario.ranking_policy
    penalty = 0
    for meeting in meetings:
        if meeting.kind != "theory":
            continue
        if policy.prefer_morning_theory and meeting.start_minute >= 13 * 60:
            penalty += meeting.duration_minutes
        if policy.prefer_evening_theory and meeting.end_minute <= 13 * 60:
            penalty += meeting.duration_minutes
    return penalty
