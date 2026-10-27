from __future__ import annotations

import json
from pathlib import Path

import pytest

from ffcs_studio.domain.models import (
    CreditBreakdown,
    CurriculumCourse,
    ImportSnapshot,
    RawVtopAllocationRow,
    SlotExpression,
    TeachingComponent,
)

ROOT = Path(__file__).resolve().parents[1]


def test_curriculum_course_keeps_unverified_type_text() -> None:
    course = CurriculumCourse(
        course_id="X-1",
        code="ABC1000",
        title="Institution-specific seminar",
        category="CUSTOM",
        raw_curriculum_type="Future Hybrid Type",
        credits=CreditBreakdown(total=1),
    )
    assert course.raw_curriculum_type == "Future Hybrid Type"
    assert course.category == "CUSTOM"


def test_slot_expression_preserves_raw_text_and_all_tokens() -> None:
    expression = SlotExpression.parse("L1 + L2+L15+L16")
    assert expression.raw == "L1 + L2+L15+L16"
    assert expression.tokens == ("L1", "L2", "L15", "L16")


def test_unknown_component_is_preserved_and_marked_for_review() -> None:
    row = RawVtopAllocationRow(1, "Z9", "NIL", "FACULTY NAME", "NEW_TYPE")
    component = TeachingComponent.from_raw_row(row)
    assert component.known_type is None
    assert component.needs_review is True
    assert component.raw_row.course_type == "NEW_TYPE"


@pytest.mark.parametrize(
    ("fixture", "expected_rows"),
    [
        ("vtop_selected_theory_only.json", 5),
        ("vtop_selected_eth_ela.json", 12),
    ],
)
def test_snapshot_round_trip_preserves_every_source_row(fixture: str, expected_rows: int) -> None:
    source = json.loads((ROOT / "examples" / fixture).read_text(encoding="utf-8"))
    snapshot = ImportSnapshot.from_mapping(source)
    assert snapshot.allocation_count == expected_rows
    assert snapshot.to_dict() == source


def test_duplicate_looking_rows_are_not_collapsed() -> None:
    source = json.loads(
        (ROOT / "examples" / "vtop_selected_theory_only.json").read_text(encoding="utf-8")
    )
    duplicate = dict(source["courses"][0]["allocations"][0])
    duplicate["source_row"] = 6
    source["courses"][0]["allocations"].append(duplicate)
    snapshot = ImportSnapshot.from_mapping(source)
    assert snapshot.allocation_count == 6
    assert snapshot.courses[0].allocations[0].slot == snapshot.courses[0].allocations[5].slot
