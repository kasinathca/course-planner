"""Complete lazy one-course candidate generation for solver use."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from ffcs_studio.domain.calendar import CalendarProfile
from ffcs_studio.domain.component_rules import (
    DEFAULT_TEMPLATES,
    AllocationType,
    CurriculumType,
    PairingState,
    allocation_type,
)
from ffcs_studio.services.slot_resolution import resolve_slot_expression
from ffcs_studio.solver.models import SolverCandidate, SolverInterval
from ffcs_studio.solver.occupancy import intervals_conflict, occupancy_mask


@dataclass(frozen=True, slots=True)
class SourceAllocation:
    allocation_id: int
    course_type: str
    slot: str
    faculty: str
    venue: str


@dataclass(frozen=True, slots=True)
class CandidateCourseSource:
    offering_id: int
    revision_id: int
    course_code: str
    curriculum_type: CurriculumType
    curriculum_verified: bool
    allocations: tuple[SourceAllocation, ...]
    pairing_states: Mapping[frozenset[int], PairingState]


@dataclass(frozen=True, slots=True)
class CandidatePolicy:
    allow_provisional_pairing: bool = False
    allow_unknown_pairing: bool = False
    allow_same_faculty_pairing: bool = False


class CompleteCandidateSource:
    """Replayable complete iterator with no display limit or eager cross-product."""

    def __init__(
        self,
        source: CandidateCourseSource,
        calendar: CalendarProfile,
        policy: CandidatePolicy,
    ) -> None:
        self.source = source
        self.calendar = calendar
        self.policy = policy

    def diagnostics(self) -> tuple[str, ...]:
        template = DEFAULT_TEMPLATES[self.source.curriculum_type]
        if not template.requirements:
            return ("curriculum component requirements are unknown",)
        groups = self._groups()
        missing = tuple(
            requirement.allocation_type.value
            for requirement, group in zip(template.requirements, groups, strict=True)
            if not group
        )
        if missing:
            return (f"missing required component(s): {', '.join(missing)}",)
        if len(groups) > 1 and not any(
            self._allowed_pair(left, right)[0] for left in groups[0] for right in groups[1]
        ):
            return ("no permitted component pairing exists under the selected policy",)
        return ()

    def __iter__(self) -> Iterator[SolverCandidate]:
        template = DEFAULT_TEMPLATES[self.source.curriculum_type]
        if not template.requirements:
            return
        groups = self._groups()
        if any(not group for group in groups):
            return
        if len(groups) == 1:
            for allocation in groups[0]:
                candidate = self._candidate((allocation,), (), verified_pairing=True)
                if candidate is not None:
                    yield candidate
            return
        if len(groups) != 2:
            return
        right_by_id = {item.allocation_id: item for item in groups[1]}
        allowed_by_left: dict[int, list[tuple[int, tuple[str, ...], bool]]] = {
            item.allocation_id: [] for item in groups[0]
        }
        for left in groups[0]:
            for right in groups[1]:
                allowed, assumptions, verified = self._allowed_pair(left, right)
                if allowed:
                    allowed_by_left[left.allocation_id].append(
                        (right.allocation_id, assumptions, verified)
                    )
        for left in groups[0]:
            for right_id, assumptions, verified in allowed_by_left[left.allocation_id]:
                candidate = self._candidate(
                    (left, right_by_id[right_id]), assumptions, verified_pairing=verified
                )
                if candidate is not None:
                    yield candidate

    def _groups(self) -> tuple[tuple[SourceAllocation, ...], ...]:
        template = DEFAULT_TEMPLATES[self.source.curriculum_type]
        groups: list[tuple[SourceAllocation, ...]] = []
        for requirement in template.requirements:
            group = tuple(
                item
                for item in self.source.allocations
                if allocation_type(item.course_type) is requirement.allocation_type
            )
            if self.source.curriculum_type is CurriculumType.TH and not group:
                group = tuple(
                    item
                    for item in self.source.allocations
                    if allocation_type(item.course_type) is AllocationType.ETH
                )
            groups.append(group)
        return tuple(groups)

    def _allowed_pair(
        self,
        left: SourceAllocation,
        right: SourceAllocation,
    ) -> tuple[bool, tuple[str, ...], bool]:
        state = self.source.pairing_states.get(
            frozenset((left.allocation_id, right.allocation_id)), PairingState.UNKNOWN
        )
        if state is PairingState.VERIFIED_FORBIDDEN:
            return False, (), False
        if state is PairingState.VERIFIED_ALLOWED:
            return True, (), True
        if state in {PairingState.PROVISIONAL, PairingState.INFERRED}:
            if self.policy.allow_provisional_pairing:
                return True, (f"component pairing is {state.value}",), False
            return False, (), False
        if (
            state is PairingState.UNKNOWN
            and self.policy.allow_same_faculty_pairing
            and _faculty_key(left.faculty) == _faculty_key(right.faculty)
        ):
            return True, ("same-faculty pairing is a provisional user-approved assumption",), False
        if state is PairingState.UNKNOWN and self.policy.allow_unknown_pairing:
            return True, ("component pairing is an explicit speculative assumption",), False
        return False, (), False

    def _candidate(
        self,
        allocations: Sequence[SourceAllocation],
        pairing_assumptions: tuple[str, ...],
        *,
        verified_pairing: bool,
    ) -> SolverCandidate | None:
        meetings: list[SolverInterval] = []
        for allocation in allocations:
            raw_type = allocation_type(allocation.course_type)
            if raw_type is AllocationType.EPJ and allocation.slot.strip().upper() == "NIL":
                continue
            resolution = resolve_slot_expression(allocation.slot, self.calendar)
            if not resolution.resolved:
                return None
            allocation_meetings = [
                SolverInterval(
                    day=int(interval.day),
                    start_minute=interval.start_minute,
                    end_minute=interval.end_minute,
                    kind=interval.kind.value,
                    allocation_id=allocation.allocation_id,
                    component_type=raw_type.value,
                    slot=allocation.slot,
                    faculty=allocation.faculty,
                    venue=allocation.venue,
                    session_id=interval.session_id,
                )
                for interval in resolution.intervals
            ]
            if raw_type is AllocationType.EPJ:
                occupied_keys = {item.physical_key() for item in meetings}
                allocation_meetings = [
                    item for item in allocation_meetings if item.physical_key() not in occupied_keys
                ]
            meetings.extend(allocation_meetings)
        unique_meetings = tuple(dict.fromkeys(meetings))
        if intervals_conflict(unique_meetings):
            return None
        assumptions = list(pairing_assumptions)
        if not self.source.curriculum_verified:
            assumptions.append("curriculum component metadata is user supplied")
        allocation_ids = tuple(item.allocation_id for item in allocations)
        identity = f"{self.source.revision_id}:" + ",".join(str(value) for value in allocation_ids)
        candidate_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        verified = verified_pairing and self.source.curriculum_verified and not assumptions
        return SolverCandidate(
            candidate_id=candidate_id,
            offering_id=self.source.offering_id,
            revision_id=self.source.revision_id,
            course_code=self.source.course_code,
            allocation_ids=allocation_ids,
            meetings=unique_meetings,
            occupancy_mask=occupancy_mask(unique_meetings),
            verification_status="verified" if verified else "provisional",
            assumptions=tuple(dict.fromkeys(assumptions)),
        )


def source_allocations(values: Sequence[Mapping[str, object]]) -> tuple[SourceAllocation, ...]:
    return tuple(
        SourceAllocation(
            allocation_id=int(str(value["allocation_id"])),
            course_type=str(value["course_type"]),
            slot=str(value["slot"]),
            faculty=str(value["faculty"]),
            venue=str(value["venue"]),
        )
        for value in values
    )


def _faculty_key(value: str) -> str:
    return " ".join(value.casefold().split())
