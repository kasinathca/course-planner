from __future__ import annotations

from ffcs_studio.domain.calendar import (
    AtomicSlot,
    CalendarProfile,
    MeetingKind,
    SourceEvidence,
    VerificationStatus,
    Weekday,
    WeeklyInterval,
)
from ffcs_studio.domain.component_rules import CurriculumType, PairingState
from ffcs_studio.services.registration_candidates import preview_candidates
from ffcs_studio.solver.candidate_source import (
    CandidateCourseSource,
    CandidatePolicy,
    CompleteCandidateSource,
    SourceAllocation,
)


def calendar() -> CalendarProfile:
    return CalendarProfile(
        calendar_id="calendar",
        campus="Vellore",
        semester_label="Synthetic",
        profile_name="Tests",
        version=1,
        timezone="Asia/Kolkata",
        verification_status=VerificationStatus.OFFICIAL_VERIFIED,
        evidence=SourceEvidence(
            "official_document", "tests", reviewed_by="tester", reviewed_at="2026-01-01"
        ),
        slots={
            "A": AtomicSlot("A", (WeeklyInterval(Weekday.MONDAY, 480, 530, MeetingKind.THEORY),)),
            "B": AtomicSlot("B", (WeeklyInterval(Weekday.TUESDAY, 480, 530, MeetingKind.THEORY),)),
            "L1": AtomicSlot(
                "L1", (WeeklyInterval(Weekday.MONDAY, 840, 890, MeetingKind.LAB, "LAB"),)
            ),
            "L2": AtomicSlot(
                "L2", (WeeklyInterval(Weekday.MONDAY, 891, 940, MeetingKind.LAB, "LAB"),)
            ),
            "L3": AtomicSlot(
                "L3", (WeeklyInterval(Weekday.WEDNESDAY, 840, 890, MeetingKind.LAB, "LAB2"),)
            ),
            "L4": AtomicSlot(
                "L4", (WeeklyInterval(Weekday.WEDNESDAY, 891, 940, MeetingKind.LAB, "LAB2"),)
            ),
        },
    )


def test_complete_source_is_not_limited_by_browser_preview() -> None:
    allocations = (
        SourceAllocation(1, "ETH", "A", "F1", "R1"),
        SourceAllocation(2, "ETH", "B", "F2", "R2"),
        SourceAllocation(3, "ELA", "L1+L2", "F1", "LAB"),
        SourceAllocation(4, "ELA", "L3+L4", "F2", "LAB"),
        SourceAllocation(5, "ELA", "L3+L4", "F3", "LAB"),
    )
    pairings = {
        frozenset((left, right)): PairingState.VERIFIED_ALLOWED
        for left in (1, 2)
        for right in (3, 4, 5)
    }
    source = CompleteCandidateSource(
        CandidateCourseSource(1, 10, "C1", CurriculumType.ETL, True, allocations, pairings),
        calendar(),
        CandidatePolicy(),
    )
    assert len(tuple(source)) == 6
    preview = preview_candidates(
        [
            {
                "allocation_id": item.allocation_id,
                "course_type": item.course_type,
                "slot": item.slot,
                "faculty": item.faculty,
                "venue": item.venue,
            }
            for item in allocations
        ],
        CurriculumType.ETL,
        pairings,
        limit=2,
    )
    assert len(preview.items) == 2
    assert preview.truncated is True


def test_strict_source_rejects_unknown_pairing() -> None:
    source = CompleteCandidateSource(
        CandidateCourseSource(
            1,
            10,
            "C1",
            CurriculumType.ETL,
            True,
            (
                SourceAllocation(1, "ETH", "A", "F1", "R1"),
                SourceAllocation(2, "ELA", "L1+L2", "F1", "LAB"),
            ),
            {},
        ),
        calendar(),
        CandidatePolicy(),
    )
    assert tuple(source) == ()
    assert "no permitted" in source.diagnostics()[0]


def test_same_faculty_pairing_is_explicitly_provisional() -> None:
    source = CompleteCandidateSource(
        CandidateCourseSource(
            1,
            10,
            "C1",
            CurriculumType.ETL,
            False,
            (
                SourceAllocation(1, "ETH", "A", " Faculty One ", "R1"),
                SourceAllocation(2, "ELA", "L1+L2", "faculty one", "LAB"),
            ),
            {},
        ),
        calendar(),
        CandidatePolicy(allow_same_faculty_pairing=True),
    )
    result = tuple(source)
    assert len(result) == 1
    assert result[0].verification_status == "provisional"
    assert any("same-faculty" in item for item in result[0].assumptions)


def test_four_slot_laboratory_retains_every_exact_interval() -> None:
    source = CompleteCandidateSource(
        CandidateCourseSource(
            1,
            10,
            "LAB",
            CurriculumType.LO,
            True,
            (SourceAllocation(1, "ELA", "L1+L2+L3+L4", "F", "LAB"),),
            {},
        ),
        calendar(),
        CandidatePolicy(),
    )
    result = tuple(source)
    assert len(result) == 1
    assert len(result[0].meetings) == 4
    assert sum(item.duration_minutes for item in result[0].meetings) == 198


def test_epj_repeated_theory_slot_does_not_duplicate_contact_time() -> None:
    source = CompleteCandidateSource(
        CandidateCourseSource(
            1,
            10,
            "PROJECT",
            CurriculumType.ETP,
            True,
            (
                SourceAllocation(1, "ETH", "A", "F", "R"),
                SourceAllocation(2, "EPJ", "A", "F", "NIL"),
            ),
            {frozenset((1, 2)): PairingState.VERIFIED_ALLOWED},
        ),
        calendar(),
        CandidatePolicy(),
    )
    result = tuple(source)
    assert len(result) == 1
    assert len(result[0].meetings) == 1
    assert result[0].meetings[0].component_type == "ETH"


def test_unknown_physical_slot_never_becomes_empty_occupancy() -> None:
    source = CompleteCandidateSource(
        CandidateCourseSource(
            1,
            10,
            "UNKNOWN",
            CurriculumType.TH,
            True,
            (SourceAllocation(1, "TH", "Z99", "F", "R"),),
            {},
        ),
        calendar(),
        CandidatePolicy(),
    )
    assert tuple(source) == ()
