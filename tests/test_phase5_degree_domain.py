from __future__ import annotations

from dataclasses import replace

import pytest

from ffcs_studio.degree.accounting import evaluate_progress, parse_milli_credit
from ffcs_studio.degree.importers import DegreeImportError, diff_legacy, parse_legacy_v6
from ffcs_studio.degree.models import (
    PROGRAMME_POLICY_2024,
    CatalogueCourse,
    CourseRecord,
    CourseStatus,
    EvidenceStatus,
    PlanDocument,
    PrerequisiteRule,
    Relationship,
    RelationshipType,
)
from ffcs_studio.degree.prerequisites import evaluate_prerequisite
from ffcs_studio.degree.recovery import RecoveryOption, RecoveryRequest, recover


def course(identity: str, code: str, category: str, credits: int | None) -> CatalogueCourse:
    return CatalogueCourse(
        canonical_id=identity,
        source_id=f"source-{identity}",
        code=code,
        title=f"Synthetic {code}",
        category=category,
        curriculum_type="TH",
        total_credits_milli=credits,
        provenance=EvidenceStatus.USER_SUPPLIED,
    )


def record(identity: str, course_id: str, semester: int, status: CourseStatus) -> CourseRecord:
    return CourseRecord(identity, course_id, semester, status)


def test_recorded_programme_targets_and_nc_ambiguity() -> None:
    targets = {item.code: item.recorded_target_milli for item in PROGRAMME_POLICY_2024.categories}
    assert targets == {
        "PC": 81_000,
        "PE": 48_000,
        "UC": 61_000,
        "UE": 12_000,
        "SPE": 18_000,
        "BC": 0,
        "NC": 5_000,
    }
    assert PROGRAMME_POLICY_2024.displayed_total_milli == 225_000
    nc = next(item for item in PROGRAMME_POLICY_2024.categories if item.code == "NC")
    assert nc.confirmed_credit_target_milli is None
    assert nc.non_credit_target_units == 5
    assert nc.counted_in_graduation is None


@pytest.mark.parametrize(
    ("value", "expected"), [("3", 3000), ("3.125", 3125), (0, 0), (None, None)]
)
def test_exact_milli_credit_parsing(value: object, expected: int | None) -> None:
    assert parse_milli_credit(value) == expected


@pytest.mark.parametrize("value", ["0.0001", "-1", "not-credit"])
def test_invalid_credit_values_fail(value: str) -> None:
    with pytest.raises(ValueError):
        parse_milli_credit(value)


def test_progress_separates_earned_enrolled_planned_unknown_and_semesters() -> None:
    courses = {
        "pc": course("pc", "SYN1001", "PC", 4000),
        "pe": course("pe", "SYN2001", "PE", 3000),
        "unknown": course("unknown", "SYN3001", "UE", None),
    }
    document = PlanDocument(
        PROGRAMME_POLICY_2024.programme_code,
        PROGRAMME_POLICY_2024.revision_code,
        (
            record("r1", "pc", 5, CourseStatus.COMPLETED),
            record("r2", "pe", 6, CourseStatus.ENROLLED),
            record("r3", "pc", 7, CourseStatus.PLANNED),
            record("r4", "unknown", 7, CourseStatus.PLANNED),
        ),
    )
    result = evaluate_progress(PROGRAMME_POLICY_2024, courses, document)
    assert result["totals"]["earned_milli"] == 4000
    assert result["totals"]["enrolled_milli"] == 3000
    assert result["totals"]["planned_milli"] == 4000
    assert result["totals"]["unknown_record_count"] == 1
    assert result["semesters"][4]["earned_milli"] == 4000
    assert result["semesters"][5]["enrolled_milli"] == 3000
    assert result["totals"]["graduation_status"] == "not_officially_verified"


def test_equivalent_completed_courses_do_not_double_count_requirement() -> None:
    courses = {
        "english-2": course("english-2", "ENG2002", "UC", 2000),
        "advanced-english": course("advanced-english", "ENG2003", "UC", 2000),
    }
    relation = Relationship(
        "english-alternative",
        RelationshipType.SAME_REQUIREMENT,
        tuple(courses),
        "technical-english-requirement",
        True,
        EvidenceStatus.USER_SUPPLIED,
    )
    document = PlanDocument(
        PROGRAMME_POLICY_2024.programme_code,
        PROGRAMME_POLICY_2024.revision_code,
        (
            record("r1", "english-2", 2, CourseStatus.COMPLETED),
            record("r2", "advanced-english", 3, CourseStatus.COMPLETED),
        ),
    )
    result = evaluate_progress(PROGRAMME_POLICY_2024, courses, document, (relation,))
    assert result["totals"]["earned_milli"] == 2000
    assert "equivalent_not_double_counted" in {item["code"] for item in result["warnings"]}


def test_category_surplus_and_configurable_semester_warning_are_not_hard_blocks() -> None:
    pe = course("pe", "SYN-PE", "PE", 49_000)
    policy = replace(PROGRAMME_POLICY_2024, planning_warning_milli=27_000)
    result = evaluate_progress(
        policy,
        {"pe": pe},
        PlanDocument(
            policy.programme_code,
            policy.revision_code,
            (record("r", "pe", 6, CourseStatus.PLANNED),),
        ),
    )
    pe_row = next(item for item in result["categories"] if item["code"] == "PE")
    assert pe_row["surplus_milli"] == 1000
    assert result["semesters"][5]["threshold_warning"] is True


def test_prerequisite_and_or_unknown_and_waiver() -> None:
    rule = PrerequisiteRule(
        "rule",
        "advanced",
        all_of=("foundation",),
        any_of=(("math-a", "math-b"),),
        minimum_semester=5,
        verified=True,
        provenance=EvidenceStatus.USER_SUPPLIED,
    )
    assert (
        evaluate_prerequisite("advanced", {"foundation", "math-b"}, 5, (rule,))["status"]
        == "satisfied"
    )
    blocked = evaluate_prerequisite("advanced", {"foundation"}, 4, (rule,))
    assert blocked["status"] == "blocked"
    assert len(blocked["missing"]) == 2
    assert (
        evaluate_prerequisite("advanced", set(), 1, (rule,), waivers={"advanced"})["status"]
        == "waived"
    )
    assert evaluate_prerequisite("unmapped", set(), 10, (rule,))["status"] == "not_verified"


def option(course_id: str, name: str, allocation: int, faculty: str, slot: str) -> RecoveryOption:
    return RecoveryOption(course_id, name, (allocation,), (faculty,), (slot,), credits_milli=3000)


def test_recovery_proves_minimum_edit_and_preserves_registered_lock() -> None:
    request = RecoveryRequest(
        intended={"must": "must-a", "optional": "opt-a"},
        options={
            "must": (
                option("must", "must-a", 1, "Faculty A", "A1"),
                option("must", "must-b", 2, "Faculty B", "B1"),
            ),
            "optional": (option("optional", "opt-a", 3, "Faculty C", "C1"),),
        },
        registered_locks={"optional": "opt-a"},
        must_take=frozenset({"must"}),
        blocked_allocations=frozenset({1}),
        priority={"optional": 1},
    )
    result = recover(request)
    assert result["status"] == "exact"
    assert result["proven_minimum"] is True
    assert result["minimum_score"][0] == 1
    assert result["results"][0]["preserved_registrations"] == ["optional"]
    assert result["results"][0]["mandatory_preserved"] is True


def test_recovery_reports_hard_lock_blocker_and_resource_limit() -> None:
    locked = RecoveryRequest(
        intended={"must": "a"},
        options={"must": (option("must", "a", 1, "F", "A1"),)},
        registered_locks={"must": "a"},
        must_take=frozenset({"must"}),
        blocked_allocations=frozenset({1}),
        priority={},
    )
    assert recover(locked)["status"] == "infeasible"
    limited = replace(
        locked,
        registered_locks={},
        blocked_allocations=frozenset(),
        options={"must": (option("must", "a", 1, "F", "A1"), option("must", "b", 2, "F", "B1"))},
        max_nodes=1,
    )
    assert recover(limited)["status"] == "best_found_so_far"
    assert recover(limited)["proven_minimum"] is False


def test_recovery_rejects_overlapping_exact_meetings() -> None:
    left = replace(option("left", "left-a", 1, "F1", "A1"), meetings=((0, 540, 590),))
    right_bad = replace(option("right", "right-a", 2, "F2", "B1"), meetings=((0, 580, 630),))
    right_good = replace(option("right", "right-b", 3, "F3", "C1"), meetings=((0, 590, 640),))
    result = recover(
        RecoveryRequest(
            intended={"left": "left-a", "right": "right-a"},
            options={"left": (left,), "right": (right_bad, right_good)},
            registered_locks={"left": "left-a"},
            must_take=frozenset({"left", "right"}),
            blocked_allocations=frozenset(),
            priority={},
        )
    )
    assert result["results"][0]["selected"][1]["option_id"] == "right-b"
    assert result["minimum_score"][0] == 1


def legacy(plan: dict[str, list[dict[str, str]]], updated_at: str) -> dict[str, object]:
    return {
        "version": 6,
        "catalog": [
            {"id": "src-a", "code": "STS3022", "title": "Synthetic Alternative A"},
            {"id": "src-b", "code": "STS3022", "title": "Synthetic Alternative B"},
        ],
        "completed": [{"courseId": "src-a"}],
        "plan": plan,
        "settings": {},
        "offerings": {},
        "updatedAt": updated_at,
    }


def test_legacy_v6_uses_source_ids_preserves_duplicate_code_and_snapshot_diff() -> None:
    first = parse_legacy_v6(
        legacy(
            {"semester9": [{"courseId": "src-b"}], "semester10": [{"courseId": "src-a"}]},
            "2026-01-01T00:00:00Z",
        ),
        source_name="first.json",
        source_sequence=1,
    )
    second = parse_legacy_v6(
        legacy({"semester7": [{"courseId": "src-b"}], "semester10": []}, "2026-02-01T00:00:00Z"),
        source_name="second.json",
        source_sequence=2,
    )
    assert first["counts"] == {"catalog": 2, "completed": 1, "planned": 2}
    assert first["duplicate_looking"] == []
    changed = diff_legacy(first, second)
    assert changed["removed"] == ["src-a"]
    assert changed["moved"] == [{"course_id": "src-b", "from_semester": 9, "to_semester": 7}]


def test_legacy_invalid_source_reference_fails_closed() -> None:
    with pytest.raises(DegreeImportError, match="unknown courseId"):
        parse_legacy_v6(
            legacy({"semester5": [{"courseId": "missing"}]}, "2026-01-01T00:00:00Z"),
            source_name="invalid.json",
            source_sequence=1,
        )
