"""Resolve slot expressions only against a selected immutable calendar version."""

from __future__ import annotations

from ffcs_studio.domain.calendar import (
    CalendarProfile,
    SlotResolution,
    UnresolvedSlot,
    WeeklyInterval,
    parse_slot_expression,
)


def resolve_slot_expression(raw: object, calendar: CalendarProfile) -> SlotResolution:
    parsed = parse_slot_expression(raw)
    if not parsed.valid:
        return SlotResolution(parsed.raw, parsed.tokens, (), (), parsed.error_message)
    intervals: list[WeeklyInterval] = []
    unresolved: list[UnresolvedSlot] = []
    for token in parsed.tokens:
        slot = calendar.slots.get(token)
        if slot is None:
            unresolved.append(UnresolvedSlot(token, "unknown_to_selected_calendar"))
        else:
            intervals.extend(slot.intervals)
    return SlotResolution(
        parsed.raw,
        parsed.tokens,
        tuple(sorted(set(intervals))),
        tuple(unresolved),
    )
