"""Pure minute-accurate weekly conflict checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ffcs_studio.domain.calendar import SlotResolution, WeeklyInterval


class ConflictStatus(StrEnum):
    CONFIRMED_CLASH = "confirmed_clash"
    NO_CLASH = "no_clash"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class IntervalClash:
    left: WeeklyInterval
    right: WeeklyInterval


@dataclass(frozen=True, slots=True)
class ClashReport:
    status: ConflictStatus
    clashes: tuple[IntervalClash, ...]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "clashes": [
                {"left": clash.left.to_dict(), "right": clash.right.to_dict()}
                for clash in self.clashes
            ],
            "reasons": list(self.reasons),
        }


def check_conflicts(left: SlotResolution, right: SlotResolution) -> ClashReport:
    reasons: list[str] = []
    for label, resolution in (("left", left), ("right", right)):
        if resolution.parse_error:
            reasons.append(f"{label}: {resolution.parse_error}")
        reasons.extend(f"{label}: unknown slot {item.token}" for item in resolution.unresolved)
    if reasons:
        return ClashReport(ConflictStatus.UNRESOLVED, (), tuple(reasons))
    clashes = tuple(
        IntervalClash(a, b) for a in left.intervals for b in right.intervals if a.overlaps(b)
    )
    return ClashReport(
        ConflictStatus.CONFIRMED_CLASH if clashes else ConflictStatus.NO_CLASH,
        clashes,
    )
