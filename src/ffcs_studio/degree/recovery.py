"""Exact lexicographic minimum-disruption registration recovery."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Protocol


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoveryOption:
    course_id: str
    option_id: str
    allocation_ids: tuple[int, ...]
    faculty: tuple[str, ...]
    slot_keys: tuple[str, ...]
    lab_sessions: int = 0
    credits_milli: int = 0
    meetings: tuple[tuple[int, int, int], ...] = ()
    evidence_status: str = "unknown"
    assumptions: tuple[str, ...] = ()
    feasible: bool = True
    blocker: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    intended: dict[str, str]
    options: dict[str, tuple[RecoveryOption, ...]]
    registered_locks: dict[str, str]
    must_take: frozenset[str]
    blocked_allocations: frozenset[int]
    priority: dict[str, int]
    max_nodes: int = 200_000
    top_k: int = 20


def request_from_payload(payload: dict[str, Any]) -> RecoveryRequest:
    options = {
        course_id: tuple(
            RecoveryOption(
                course_id=course_id,
                option_id=str(item["option_id"]),
                allocation_ids=tuple(int(value) for value in item.get("allocation_ids", [])),
                faculty=tuple(str(value) for value in item.get("faculty", [])),
                slot_keys=tuple(str(value) for value in item.get("slot_keys", [])),
                lab_sessions=int(item.get("lab_sessions", 0)),
                credits_milli=int(item.get("credits_milli", 0)),
                meetings=tuple(
                    (
                        int(meeting["day"]),
                        int(meeting["start_minute"]),
                        int(meeting["end_minute"]),
                    )
                    for meeting in item.get("meetings", [])
                ),
                evidence_status=str(item.get("evidence_status", "unknown")),
                assumptions=tuple(str(value) for value in item.get("assumptions", [])),
                feasible=bool(item.get("feasible", True)),
                blocker=item.get("blocker"),
            )
            for item in values
        )
        for course_id, values in payload["options"].items()
    }
    return RecoveryRequest(
        intended={str(key): str(value) for key, value in payload.get("intended", {}).items()},
        options=options,
        registered_locks={
            str(key): str(value) for key, value in payload.get("registered_locks", {}).items()
        },
        must_take=frozenset(str(value) for value in payload.get("must_take", [])),
        blocked_allocations=frozenset(
            int(value) for value in payload.get("blocked_allocations", [])
        ),
        priority={str(key): int(value) for key, value in payload.get("priority", {}).items()},
        max_nodes=int(payload.get("max_nodes", 200_000)),
        top_k=int(payload.get("top_k", 20)),
    )


def recover(
    request: RecoveryRequest, cancellation: CancellationSignal | None = None
) -> dict[str, Any]:
    courses = sorted(request.options)
    choices: list[tuple[RecoveryOption | None, ...]] = []
    blockers: list[dict[str, str]] = []
    for course in courses:
        valid = tuple(
            option
            for option in request.options[course]
            if _allowed(option, request.blocked_allocations)
        )
        locked = request.registered_locks.get(course)
        if locked is not None:
            valid = tuple(option for option in valid if option.option_id == locked)
            if not valid:
                blockers.append(
                    {
                        "course_id": course,
                        "code": "registered_lock_unavailable",
                        "message": f"Registered lock {locked} has no valid option.",
                    }
                )
        course_choices: tuple[RecoveryOption | None, ...] = (
            valid if course in request.must_take else (*valid, None)
        )
        if not course_choices:
            blockers.append(
                {
                    "course_id": course,
                    "code": "no_valid_option",
                    "message": "No valid registration option remains.",
                }
            )
        choices.append(course_choices)
    if blockers:
        return {
            "status": "infeasible",
            "proven_minimum": True,
            "nodes": 0,
            "blockers": blockers,
            "results": [],
        }
    nodes = 0
    best_score: tuple[int, ...] | None = None
    results: list[dict[str, Any]] = []
    exhausted = True
    cancelled = False
    for combination in product(*choices):
        if cancellation is not None and cancellation.is_set():
            exhausted = False
            cancelled = True
            break
        nodes += 1
        if nodes > request.max_nodes:
            exhausted = False
            break
        selected = [option for option in combination if option is not None]
        if not _compatible(selected):
            continue
        score = _score(courses, combination, request)
        if best_score is None or score < best_score:
            best_score = score
            results = [_result(courses, combination, request, score)]
        elif score == best_score:
            results.append(_result(courses, combination, request, score))
    results.sort(key=lambda item: (item["score"], item["assignment_key"]))
    return {
        "status": "exact" if exhausted else ("cancelled" if cancelled else "best_found_so_far"),
        "proven_minimum": exhausted,
        "nodes": nodes,
        "minimum_score": list(best_score) if best_score is not None else None,
        "blockers": []
        if results
        else [
            {
                "code": "no_compatible_combination",
                "message": "Every remaining option combination conflicts.",
            }
        ],
        "results": results[: request.top_k],
    }


def _allowed(option: RecoveryOption, blocked: frozenset[int]) -> bool:
    return option.feasible and not blocked.intersection(option.allocation_ids)


def _compatible(options: list[RecoveryOption]) -> bool:
    seen: set[int] = set()
    for option in options:
        current = set(option.allocation_ids)
        if seen & current:
            return False
        seen |= current
    meetings = [meeting for option in options for meeting in option.meetings]
    for index, left in enumerate(meetings):
        for right in meetings[index + 1 :]:
            if left[0] == right[0] and left[1] < right[2] and right[1] < left[2]:
                return False
    return True


def _score(
    courses: list[str], combination: tuple[RecoveryOption | None, ...], request: RecoveryRequest
) -> tuple[int, ...]:
    changed = faculty_changed = slot_changed = dropped_priority = labs = 0
    for course, option in zip(courses, combination, strict=True):
        intended_id = request.intended.get(course)
        if option is None:
            changed += 1
            dropped_priority += max(1, 100 - request.priority.get(course, 50))
            continue
        if intended_id is not None and option.option_id != intended_id:
            changed += 1
            intended = next(
                (item for item in request.options[course] if item.option_id == intended_id), None
            )
            if intended is None or intended.faculty != option.faculty:
                faculty_changed += 1
            if intended is None or intended.slot_keys != option.slot_keys:
                slot_changed += 1
        labs += option.lab_sessions
    return changed, faculty_changed, slot_changed, dropped_priority, labs


def _result(
    courses: list[str],
    combination: tuple[RecoveryOption | None, ...],
    request: RecoveryRequest,
    score: tuple[int, ...],
) -> dict[str, Any]:
    selected = {
        course: option
        for course, option in zip(courses, combination, strict=True)
        if option is not None
    }
    changes = []
    for course in courses:
        before = request.intended.get(course)
        after = selected.get(course)
        after_id = after.option_id if after else None
        if before != after_id:
            changes.append(
                {"course_id": course, "from_option_id": before, "to_option_id": after_id}
            )
    return {
        "score": list(score),
        "assignment_key": "|".join(
            f"{course}:{selected[course].option_id if course in selected else '-'}"
            for course in courses
        ),
        "changes": changes,
        "preserved_registrations": sorted(
            course
            for course, option_id in request.registered_locks.items()
            if selected.get(course) and selected[course].option_id == option_id
        ),
        "selected": [
            {
                "course_id": course,
                "option_id": option.option_id,
                "allocation_ids": list(option.allocation_ids),
                "faculty": list(option.faculty),
                "slot_keys": list(option.slot_keys),
                "lab_sessions": option.lab_sessions,
                "credits_milli": option.credits_milli,
                "meetings": [list(meeting) for meeting in option.meetings],
                "evidence_status": option.evidence_status,
                "assumptions": list(option.assumptions),
            }
            for course, option in selected.items()
        ],
        "dropped_courses": sorted(set(courses) - set(selected)),
        "credit_difference_milli": sum(option.credits_milli for option in selected.values())
        - sum(
            next(
                (
                    item.credits_milli
                    for item in request.options[course]
                    if item.option_id == option_id
                ),
                0,
            )
            for course, option_id in request.intended.items()
        ),
        "lab_sessions": sum(option.lab_sessions for option in selected.values()),
        "mandatory_preserved": request.must_take <= set(selected),
    }
