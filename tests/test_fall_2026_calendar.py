from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest

from ffcs_studio.domain.calendar import CalendarProfile, MeetingKind, Weekday
from ffcs_studio.domain.conflicts import ConflictStatus, check_conflicts
from ffcs_studio.domain.workload import calculate_workload
from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.database import Database
from ffcs_studio.services.calendar_service import CalendarService
from ffcs_studio.services.slot_resolution import resolve_slot_expression
from ffcs_studio.services.timetable_validation import validate_registered_timetable

ROOT = Path(__file__).resolve().parents[1]
FALL_CALENDAR = ROOT / "examples" / "fall_2026-27_weekday_slot_calendar_USER_SUPPLIED.json"
SYNTHETIC_CALENDAR = ROOT / "examples" / "sample_slot_calendar_DRAFT.json"


@pytest.fixture
def fall_calendar(tmp_path: Path) -> CalendarProfile:
    database = Database(tmp_path / "calendar.sqlite3")
    database.initialize()
    repository = CalendarRepository(database)
    schema = json.loads(
        resources.files("ffcs_studio.resources.schemas")
        .joinpath("slot-calendar.schema.json")
        .read_text(encoding="utf-8")
    )
    service = CalendarService(repository, schema)
    validated = service.validate(json.loads(FALL_CALENDAR.read_text(encoding="utf-8")))
    assert validated["calendar"]["verification_status"] == "user_supplied"
    previewed = service.preview(validated["validation_id"])
    assert previewed["slot_count"] == 101
    assert previewed["interval_count"] == 115
    committed = service.commit(previewed["preview_id"], make_active=True)
    result = repository.get(committed["calendar_id"])
    assert result is not None
    return result


def interval_key(interval) -> tuple[Weekday, int, int]:
    return interval.day, interval.start_minute, interval.end_minute


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "A1+TA1",
            {
                (Weekday.MONDAY, 480, 530),
                (Weekday.WEDNESDAY, 540, 590),
                (Weekday.FRIDAY, 600, 650),
            },
        ),
        (
            "B1+TB1",
            {
                (Weekday.MONDAY, 660, 710),
                (Weekday.TUESDAY, 480, 530),
                (Weekday.THURSDAY, 540, 590),
            },
        ),
        (
            "A2+TA2",
            {
                (Weekday.MONDAY, 840, 890),
                (Weekday.WEDNESDAY, 900, 950),
                (Weekday.FRIDAY, 960, 1010),
            },
        ),
    ],
)
def test_known_combined_theory_resolutions(
    fall_calendar: CalendarProfile,
    expression: str,
    expected: set[tuple[Weekday, int, int]],
) -> None:
    result = resolve_slot_expression(expression, fall_calendar)
    assert result.resolved
    assert {interval_key(interval) for interval in result.intervals} == expected


@pytest.mark.parametrize(
    ("expression", "expected", "expected_minutes"),
    [
        (
            "L49+L50",
            {(Weekday.THURSDAY, 840, 890), (Weekday.THURSDAY, 891, 940)},
            99,
        ),
        (
            "L51+L52",
            {(Weekday.THURSDAY, 951, 1000), (Weekday.THURSDAY, 1001, 1050)},
            98,
        ),
    ],
)
def test_lab_pairs_preserve_one_minute_break_and_one_session(
    fall_calendar: CalendarProfile,
    expression: str,
    expected: set[tuple[Weekday, int, int]],
    expected_minutes: int,
) -> None:
    result = resolve_slot_expression(expression, fall_calendar)
    assert {interval_key(interval) for interval in result.intervals} == expected
    workload = calculate_workload(result.intervals)
    assert workload.weekly_minutes == expected_minutes
    assert workload.meeting_count == 2
    assert workload.session_count == 1


def test_lab_expression_across_days_has_two_sessions(fall_calendar: CalendarProfile) -> None:
    result = resolve_slot_expression("L1+L2+L15+L16", fall_calendar)
    assert {interval_key(interval) for interval in result.intervals} == {
        (Weekday.MONDAY, 480, 530),
        (Weekday.MONDAY, 531, 580),
        (Weekday.WEDNESDAY, 591, 640),
        (Weekday.WEDNESDAY, 641, 690),
    }
    workload = calculate_workload(result.intervals)
    assert workload.weekly_minutes == 197
    assert workload.session_count == 2


@pytest.mark.parametrize(
    ("left", "right", "status"),
    [
        ("A1", "L1", ConflictStatus.CONFIRMED_CLASH),
        ("A1", "L14", ConflictStatus.CONFIRMED_CLASH),
        ("TA1", "L27", ConflictStatus.CONFIRMED_CLASH),
        ("A1", "A2", ConflictStatus.NO_CLASH),
    ],
)
def test_known_fall_clash_results(
    fall_calendar: CalendarProfile, left: str, right: str, status: ConflictStatus
) -> None:
    report = check_conflicts(
        resolve_slot_expression(left, fall_calendar),
        resolve_slot_expression(right, fall_calendar),
    )
    assert report.status is status


def test_calendar_coverage_and_special_semantics(fall_calendar: CalendarProfile) -> None:
    assert len(fall_calendar.slots) == 101
    assert sum(len(slot.intervals) for slot in fall_calendar.slots.values()) == 115
    assert {f"L{number}" for number in range(1, 61)} <= set(fall_calendar.slots)
    assert all(
        interval.day <= Weekday.FRIDAY
        for slot in fall_calendar.slots.values()
        for interval in slot.intervals
    )
    assert "TBB1" not in fall_calendar.slots
    assert "TDD1" not in fall_calendar.slots
    assert all(
        interval.kind is MeetingKind.OTHER
        for code, slot in fall_calendar.slots.items()
        if code.startswith("V")
        for interval in slot.intervals
    )


def test_api_interval_representation_has_readable_day_and_clock(
    fall_calendar: CalendarProfile,
) -> None:
    interval = resolve_slot_expression("L49", fall_calendar).intervals[0].to_dict()
    assert interval["day_name"] == "Thursday"
    assert interval["start_time"] == "14:00"
    assert interval["end_time"] == "14:50"
    assert interval["duration_minutes"] == 50


def test_nil_is_unscheduled_only_for_explicit_online_component(
    fall_calendar: CalendarProfile,
) -> None:
    components = [
        {"course_code": "SAFE1", "slot": "A1+TA1", "component_type": "ETH", "credits": 3},
        {"course_code": "SAFE1", "slot": "L51+L52", "component_type": "ELA", "credits": 1},
        {"course_code": "SAFE2", "slot": "NIL", "component_type": "ONLINE", "credits": 4},
    ]
    result = validate_registered_timetable(components, fall_calendar)
    assert result.valid
    assert result.component_count == 3
    assert result.course_count == 2
    assert result.total_credits == 8
    assert result.scheduled_component_count == 2
    assert result.unscheduled_component_count == 1
    assert result.interval_count == 5
    assert result.contact_minutes == 248
    assert result.workload.session_count == 4


def test_nil_does_not_become_an_atomic_calendar_slot(fall_calendar: CalendarProfile) -> None:
    assert "NIL" not in fall_calendar.slots
    result = validate_registered_timetable(
        [{"course_code": "SAFE", "slot": "NIL", "component_type": "ETH", "credits": 1}],
        fall_calendar,
    )
    assert not result.valid
    assert result.issues[0].code == "nil_for_scheduled_component"


def test_unknown_slot_keeps_timetable_incomplete(fall_calendar: CalendarProfile) -> None:
    result = validate_registered_timetable(
        [{"course_code": "SAFE", "slot": "TBB1", "component_type": "TH", "credits": 3}],
        fall_calendar,
    )
    assert not result.valid
    assert result.issues[0].code == "unresolved_slot"


def test_registration_check_detects_minute_overlap(fall_calendar: CalendarProfile) -> None:
    result = validate_registered_timetable(
        [
            {"course_code": "SAFE1", "slot": "A1", "component_type": "TH", "credits": 3},
            {"course_code": "SAFE2", "slot": "L1", "component_type": "ELA", "credits": 1},
        ],
        fall_calendar,
    )
    assert not result.valid
    assert result.conflict_pairs == ((1, 2),)


def test_active_calendar_selection_is_scoped_by_semester(tmp_path: Path) -> None:
    database = Database(tmp_path / "scoped.sqlite3")
    database.initialize()
    repository = CalendarRepository(database)
    schema = json.loads(
        resources.files("ffcs_studio.resources.schemas")
        .joinpath("slot-calendar.schema.json")
        .read_text(encoding="utf-8")
    )
    service = CalendarService(repository, schema)
    for path in (FALL_CALENDAR, SYNTHETIC_CALENDAR):
        validated = service.validate(json.loads(path.read_text(encoding="utf-8")))
        previewed = service.preview(validated["validation_id"])
        service.commit(previewed["preview_id"], make_active=True)
    fall = repository.active_for("Vellore", "Fall Semester 2026-27")
    synthetic = repository.active_for("Vellore", "EXAMPLE_ONLY_NOT_OFFICIAL")
    assert fall is not None and synthetic is not None
    assert fall.calendar_id != synthetic.calendar_id
