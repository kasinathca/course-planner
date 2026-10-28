from __future__ import annotations

from ffcs_studio.domain.component_rules import (
    AllocationType,
    CurriculumType,
    PairingState,
    allocation_type,
)
from ffcs_studio.services.registration_candidates import build_candidates

ALLOCATIONS = [
    {"allocation_id": 1, "course_type": "ETH", "slot": "A1", "faculty": "F1", "venue": "R1"},
    {"allocation_id": 2, "course_type": "ETH", "slot": "B1", "faculty": "F2", "venue": "R2"},
    {"allocation_id": 3, "course_type": "ELA", "slot": "L1+L2", "faculty": "F1", "venue": "LAB"},
    {"allocation_id": 4, "course_type": "EPJ", "slot": "P1", "faculty": "F1", "venue": "PROJECT"},
]


def test_curriculum_and_allocation_vocabularies_are_distinct() -> None:
    assert CurriculumType.ETL.value == "ETL"
    assert AllocationType.ELA.value == "ELA"
    assert "ETL" not in {item.value for item in AllocationType}


def test_unknown_allocation_type_remains_unknown() -> None:
    assert allocation_type("mystery") is AllocationType.UNKNOWN


def test_multicomponent_candidate_requires_pairing_rule() -> None:
    candidates = build_candidates(ALLOCATIONS, CurriculumType.ETL, {})
    assert candidates[0].status == "unresolved"
    assert not candidates[0].allocations


def test_verified_pairing_creates_verified_candidate_only() -> None:
    candidates = build_candidates(
        ALLOCATIONS,
        CurriculumType.ETL,
        {frozenset((1, 3)): PairingState.VERIFIED_ALLOWED},
    )
    assert len(candidates) == 1
    assert candidates[0].status == "verified"
    assert [item.allocation_id for item in candidates[0].allocations] == [1, 3]


def test_forbidden_pairing_is_never_emitted() -> None:
    candidates = build_candidates(
        ALLOCATIONS,
        CurriculumType.ETL,
        {frozenset((1, 3)): PairingState.VERIFIED_FORBIDDEN},
    )
    assert candidates[0].status == "unresolved"


def test_provisional_pairing_is_labeled() -> None:
    candidates = build_candidates(
        ALLOCATIONS,
        CurriculumType.ETP,
        {frozenset((1, 4)): PairingState.PROVISIONAL},
    )
    assert candidates[0].status == "provisional"


def test_unknown_curriculum_returns_reviewable_rows_not_combinations() -> None:
    candidates = build_candidates(ALLOCATIONS, CurriculumType.UNKNOWN, {})
    assert len(candidates) == len(ALLOCATIONS)
    assert all(candidate.status == "needs_review" for candidate in candidates)
    assert all(len(candidate.allocations) == 1 for candidate in candidates)


def test_candidate_count_is_bounded() -> None:
    candidates = build_candidates(ALLOCATIONS, CurriculumType.UNKNOWN, {}, limit=2)
    assert len(candidates) == 2


def test_epj_is_not_classified_as_lab() -> None:
    assert allocation_type("EPJ") is AllocationType.EPJ
    assert allocation_type("EPJ") is not AllocationType.ELA


def test_th_template_accepts_explicit_eth_when_no_th_row_exists() -> None:
    candidates = build_candidates(ALLOCATIONS, CurriculumType.TH, {})
    assert len(candidates) == 2
    assert all(item.allocations[0].course_type is AllocationType.ETH for item in candidates)
