from __future__ import annotations

import pytest

from ffcs_studio.domain.calendar import (
    AtomicSlot,
    CalendarProfile,
    MeetingKind,
    SourceEvidence,
    VerificationStatus,
    Weekday,
    WeeklyInterval,
    parse_slot_expression,
)
from ffcs_studio.domain.conflicts import ConflictStatus, check_conflicts
from ffcs_studio.domain.workload import calculate_workload
from ffcs_studio.services.slot_resolution import resolve_slot_expression


def calendar() -> CalendarProfile:
    return CalendarProfile(
        "calendar-1",
        "Vellore",
        "Synthetic",
        "Tests only",
        1,
        "Asia/Kolkata",
        VerificationStatus.DRAFT_UNVERIFIED,
        SourceEvidence("synthetic_test", "tests/test_phase2_calendar_domain.py"),
        {
            "A1": AtomicSlot(
                "A1",
                (
                    WeeklyInterval(Weekday.MONDAY, 480, 530, MeetingKind.THEORY),
                    WeeklyInterval(Weekday.WEDNESDAY, 540, 590, MeetingKind.THEORY),
                ),
            ),
            "L1": AtomicSlot(
                "L1",
                (WeeklyInterval(Weekday.MONDAY, 500, 550, MeetingKind.LAB, "lab-1"),),
            ),
            "L2": AtomicSlot(
                "L2",
                (WeeklyInterval(Weekday.MONDAY, 550, 600, MeetingKind.LAB, "lab-1"),),
            ),
            "B1": AtomicSlot(
                "B1", (WeeklyInterval(Weekday.TUESDAY, 480, 530, MeetingKind.THEORY),)
            ),
        },
    )


@pytest.mark.parametrize(
    ("raw", "valid", "code"),
    [
        ("A1", True, None),
        (" A1 + L1 ", True, None),
        ("", False, "blank_expression"),
        ("   ", False, "blank_expression"),
        ("A1+", False, "malformed_expression"),
        ("+A1", False, "malformed_expression"),
        ("A1++L1", False, "malformed_expression"),
        (None, False, "invalid_type"),
    ],
)
def test_strict_slot_parser(raw: object, valid: bool, code: str | None) -> None:
    result = parse_slot_expression(raw)
    assert result.valid is valid
    assert result.error_code == code


def test_parser_preserves_exact_raw_and_order() -> None:
    result = parse_slot_expression(" A1 + L1 +A1 ")
    assert result.raw == " A1 + L1 +A1 "
    assert result.tokens == ("A1", "L1", "A1")


def test_unknown_slot_is_distinct_from_malformed_expression() -> None:
    unknown = resolve_slot_expression("Z99", calendar())
    malformed = resolve_slot_expression("A1++L1", calendar())
    assert unknown.parse_error is None
    assert unknown.unresolved[0].reason == "unknown_to_selected_calendar"
    assert malformed.parse_error is not None
    assert not malformed.unresolved


def test_resolver_unions_multi_day_and_combined_slots() -> None:
    result = resolve_slot_expression("A1+B1", calendar())
    assert result.resolved
    assert len(result.intervals) == 3
    assert {interval.day for interval in result.intervals} == {
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
    }


def test_resolver_deduplicates_repeated_atomic_slot_intervals() -> None:
    result = resolve_slot_expression("A1+A1", calendar())
    assert len(result.intervals) == 2


def test_minute_overlap_is_confirmed_clash() -> None:
    report = check_conflicts(
        resolve_slot_expression("A1", calendar()), resolve_slot_expression("L1", calendar())
    )
    assert report.status is ConflictStatus.CONFIRMED_CLASH
    assert len(report.clashes) == 1


def test_touching_half_open_boundaries_do_not_clash() -> None:
    report = check_conflicts(
        resolve_slot_expression("L1", calendar()), resolve_slot_expression("L2", calendar())
    )
    assert report.status is ConflictStatus.NO_CLASH


def test_different_days_do_not_clash_at_same_clock_time() -> None:
    report = check_conflicts(
        resolve_slot_expression("A1", calendar()), resolve_slot_expression("B1", calendar())
    )
    assert report.status is ConflictStatus.NO_CLASH


def test_unknown_prevents_false_no_clash() -> None:
    report = check_conflicts(
        resolve_slot_expression("Z99", calendar()), resolve_slot_expression("B1", calendar())
    )
    assert report.status is ConflictStatus.UNRESOLVED


def test_official_status_requires_reviewed_official_evidence() -> None:
    with pytest.raises(ValueError, match="official_verified"):
        CalendarProfile(
            "x",
            "Vellore",
            "Winter",
            "Claim",
            1,
            "Asia/Kolkata",
            VerificationStatus.OFFICIAL_VERIFIED,
            SourceEvidence("user_claim", "trust me"),
            {"A1": calendar().slots["A1"]},
        )


def test_workload_uses_interval_union_and_explicit_sessions() -> None:
    intervals = (
        WeeklyInterval(Weekday.MONDAY, 480, 530, MeetingKind.LAB, "lab-1"),
        WeeklyInterval(Weekday.MONDAY, 530, 580, MeetingKind.LAB, "lab-1"),
        WeeklyInterval(Weekday.TUESDAY, 480, 530, MeetingKind.PROJECT, "project-1"),
    )
    workload = calculate_workload(intervals)
    assert workload.weekly_minutes == 150
    assert workload.meeting_count == 3
    assert workload.session_count == 2


def test_workload_deduplicates_duplicate_intervals() -> None:
    interval = WeeklyInterval(Weekday.MONDAY, 480, 530, MeetingKind.PROJECT)
    workload = calculate_workload((interval, interval))
    assert workload.weekly_minutes == 50
    assert workload.meeting_count == 1
