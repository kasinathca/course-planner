"""Bounded one-course registration candidates with explicit uncertainty."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import product
from typing import Any

from ffcs_studio.domain.component_rules import (
    DEFAULT_TEMPLATES,
    AllocationType,
    CurriculumType,
    PairingState,
    allocation_type,
)


@dataclass(frozen=True, slots=True)
class AllocationChoice:
    allocation_id: int
    course_type: AllocationType
    slot: str
    faculty: str
    venue: str


@dataclass(frozen=True, slots=True)
class RegistrationCandidate:
    allocations: tuple[AllocationChoice, ...]
    status: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "allocations": [
                {
                    "allocation_id": item.allocation_id,
                    "course_type": item.course_type.value,
                    "slot": item.slot,
                    "faculty": item.faculty,
                    "venue": item.venue,
                }
                for item in self.allocations
            ],
        }


def build_candidates(
    allocations: Iterable[Mapping[str, object]],
    curriculum_type: CurriculumType,
    pairing_states: Mapping[frozenset[int], PairingState],
    *,
    limit: int = 200,
) -> tuple[RegistrationCandidate, ...]:
    if not 1 <= limit <= 1000:
        raise ValueError("candidate limit must be between 1 and 1000")
    choices = tuple(
        AllocationChoice(
            allocation_id=int(str(item["allocation_id"])),
            course_type=allocation_type(str(item["course_type"])),
            slot=str(item["slot"]),
            faculty=str(item["faculty"]),
            venue=str(item["venue"]),
        )
        for item in allocations
    )
    template = DEFAULT_TEMPLATES[curriculum_type]
    if not template.requirements:
        return tuple(
            RegistrationCandidate((item,), "needs_review", ("curriculum type is unknown",))
            for item in choices[:limit]
        )
    groups = []
    for requirement in template.requirements:
        group = tuple(item for item in choices if item.course_type is requirement.allocation_type)
        if curriculum_type is CurriculumType.TH and not group:
            group = tuple(item for item in choices if item.course_type is AllocationType.ETH)
        groups.append(group)
    if any(not group for group in groups):
        missing = tuple(
            requirement.allocation_type.value
            for requirement, group in zip(template.requirements, groups, strict=True)
            if not group
        )
        return (
            RegistrationCandidate(
                (), "incomplete", (f"missing required component(s): {', '.join(missing)}",)
            ),
        )
    candidates: list[RegistrationCandidate] = []
    for combination in product(*groups):
        if len(combination) == 1:
            candidates.append(RegistrationCandidate(combination, "provisional", (template.source,)))
        else:
            states = [
                pairing_states.get(
                    frozenset(
                        (combination[index].allocation_id, combination[index + 1].allocation_id)
                    ),
                    PairingState.UNKNOWN,
                )
                for index in range(len(combination) - 1)
            ]
            if PairingState.VERIFIED_FORBIDDEN in states or PairingState.UNKNOWN in states:
                continue
            status = (
                "verified"
                if all(state is PairingState.VERIFIED_ALLOWED for state in states)
                else "provisional"
            )
            candidates.append(
                RegistrationCandidate(
                    combination,
                    status,
                    tuple(f"pairing: {state.value}" for state in states),
                )
            )
        if len(candidates) >= limit:
            break
    if not candidates:
        return (
            RegistrationCandidate(
                (),
                "unresolved",
                ("no explicit allowed pairing rules exist for this offering revision",),
            ),
        )
    return tuple(candidates)
