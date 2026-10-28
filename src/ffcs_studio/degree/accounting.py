"""Exact programme and semester accounting."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any

from ffcs_studio.degree.models import (
    CatalogueCourse,
    CourseRecord,
    CourseStatus,
    PlanDocument,
    ProgrammePolicy,
    Relationship,
    RelationshipType,
)


def parse_milli_credit(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("credit value must be decimal") from exc
    milli = decimal * 1000
    if decimal < 0 or milli != milli.to_integral_value():
        raise ValueError("credit value must be non-negative with at most three decimals")
    return int(milli)


def format_credit(milli: int | None) -> str | None:
    if milli is None:
        return None
    value = Decimal(milli) / 1000
    return format(value.normalize(), "f")


def evaluate_progress(
    policy: ProgrammePolicy,
    courses: dict[str, CatalogueCourse],
    document: PlanDocument,
    relationships: tuple[Relationship, ...] = (),
) -> dict[str, Any]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    semester: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unknown: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    counted_completed: set[str] = set()
    requirement_winners: dict[str, str] = {}
    requirement_by_course: dict[str, str] = {}
    exclusive_groups: list[set[str]] = []
    for relation in relationships:
        if not relation.verified:
            continue
        if relation.relationship_type in {
            RelationshipType.EQUIVALENT,
            RelationshipType.SAME_REQUIREMENT,
            RelationshipType.BASKET,
        }:
            key = relation.requirement_key or relation.relationship_id
            for course_id in relation.course_ids:
                requirement_by_course[course_id] = key
        if relation.relationship_type == RelationshipType.MUTUALLY_EXCLUSIVE:
            exclusive_groups.append(set(relation.course_ids))

    active_by_course: dict[str, list[CourseRecord]] = defaultdict(list)
    for record in document.records:
        active_by_course[record.course_id].append(record)
    for course_id, records in active_by_course.items():
        active = [
            r for r in records if r.status not in {CourseStatus.WITHDRAWN, CourseStatus.FAILED}
        ]
        if len(active) > 1:
            warnings.append(
                {
                    "code": "duplicate_course",
                    "message": f"{course_id} appears in multiple active records.",
                }
            )

    active_ids = {
        r.course_id
        for r in document.records
        if r.status not in {CourseStatus.WITHDRAWN, CourseStatus.FAILED}
    }
    for group in exclusive_groups:
        selected = sorted(group & active_ids)
        if len(selected) > 1:
            warnings.append(
                {
                    "code": "mutual_exclusion",
                    "message": f"Mutually exclusive courses selected: {', '.join(selected)}.",
                }
            )

    ordered = sorted(document.records, key=lambda r: (r.semester, r.attempt, r.record_id))
    for record in ordered:
        course = courses.get(record.course_id)
        if course is None:
            unknown.append(
                {
                    "record_id": record.record_id,
                    "course_id": record.course_id,
                    "reason": "catalogue_missing",
                }
            )
            continue
        category = record.intended_category or course.category
        credits = course.total_credits_milli
        if credits is None:
            unknown.append(
                {
                    "record_id": record.record_id,
                    "course_id": record.course_id,
                    "reason": "credits_unknown",
                }
            )
            continue
        if record.status in {CourseStatus.WITHDRAWN, CourseStatus.FAILED}:
            continue
        status_key = {
            CourseStatus.COMPLETED: "earned_milli",
            CourseStatus.ENROLLED: "enrolled_milli",
            CourseStatus.PLANNED: "planned_milli",
            CourseStatus.TENTATIVE: "planned_milli",
        }[record.status]
        if record.status == CourseStatus.COMPLETED:
            requirement_key = requirement_by_course.get(record.course_id)
            if record.course_id in counted_completed:
                warnings.append(
                    {
                        "code": "repeat_not_double_counted",
                        "message": f"Repeated completion {course.code} was not counted twice.",
                    }
                )
                continue
            if requirement_key and requirement_key in requirement_winners:
                warnings.append(
                    {
                        "code": "equivalent_not_double_counted",
                        "message": f"{course.code} does not satisfy {requirement_key} twice.",
                    }
                )
                continue
            counted_completed.add(record.course_id)
            if requirement_key:
                requirement_winners[requirement_key] = record.course_id
        buckets[category][status_key] += credits
        semester[record.semester][status_key] += credits
        semester[record.semester][f"category_{category}_{status_key}"] += credits

    category_rows: list[dict[str, Any]] = []
    for requirement in policy.categories:
        values = buckets[requirement.code]
        earned = values["earned_milli"]
        enrolled = values["enrolled_milli"]
        planned = values["planned_milli"]
        target = requirement.confirmed_credit_target_milli
        needed = None if target is None else max(0, target - earned)
        projected = None if target is None else max(0, target - earned - enrolled - planned)
        surplus = 0 if target is None else max(0, earned + enrolled + planned - target)
        if target is None:
            status = "pending_classification"
        elif earned >= target:
            status = "earned"
        elif earned + enrolled + planned >= target:
            status = "projected"
        else:
            status = "remaining"
        category_rows.append(
            {
                **asdict(requirement),
                "earned_milli": earned,
                "enrolled_milli": enrolled,
                "planned_milli": planned,
                "needed_after_earned_milli": needed,
                "projected_remaining_milli": projected,
                "surplus_milli": surplus,
                "status": status,
            }
        )
        if surplus:
            warnings.append(
                {
                    "code": "category_surplus",
                    "message": (
                        f"{requirement.code} has a projected surplus of "
                        f"{format_credit(surplus)} credits."
                    ),
                }
            )

    semester_rows = []
    cumulative = {"earned_milli": 0, "enrolled_milli": 0, "planned_milli": 0}
    warning_limit = policy.planning_warning_milli
    for number in range(1, 11):
        values = semester[number]
        row: dict[str, Any] = {
            "semester": number,
            **values,
            "earned_milli": values["earned_milli"],
            "enrolled_milli": values["enrolled_milli"],
            "planned_milli": values["planned_milli"],
        }
        total = values["earned_milli"] + values["enrolled_milli"] + values["planned_milli"]
        row["known_workload_milli"] = total
        for key in cumulative:
            cumulative[key] += values[key]
            row[f"cumulative_{key}"] = cumulative[key]
        row["threshold_warning"] = bool(warning_limit is not None and total > warning_limit)
        if row["threshold_warning"]:
            warnings.append(
                {
                    "code": "semester_threshold",
                    "message": (
                        f"Semester {number} exceeds the configurable "
                        f"{format_credit(warning_limit)}-credit warning threshold."
                    ),
                }
            )
        semester_rows.append(row)

    totals = {
        key: sum(row[key] for row in category_rows)
        for key in ("earned_milli", "enrolled_milli", "planned_milli")
    }
    totals["known_workload_milli"] = sum(totals.values())
    totals["unknown_record_count"] = len(unknown)
    confirmed_targets = [
        r.confirmed_credit_target_milli
        for r in policy.categories
        if r.confirmed_credit_target_milli is not None
    ]
    totals["remaining_confirmed_milli"] = max(0, sum(confirmed_targets) - totals["earned_milli"])
    totals["graduation_status"] = (
        "not_officially_verified"
        if any(r.counted_in_graduation is None for r in policy.categories)
        else "requirements_evaluated"
    )
    return {
        "programme": asdict(policy),
        "totals": totals,
        "categories": category_rows,
        "semesters": semester_rows,
        "unknown": unknown,
        "warnings": warnings,
    }
