"""Workload metrics derived from resolved meetings, never slot-name heuristics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ffcs_studio.domain.calendar import WeeklyInterval


@dataclass(frozen=True, slots=True)
class Workload:
    weekly_minutes: int
    meeting_count: int
    session_count: int


def calculate_workload(intervals: Iterable[WeeklyInterval]) -> Workload:
    """Union overlapping intervals and count explicit session blocks."""

    unique = sorted(set(intervals), key=lambda item: (item.day, item.start_minute, item.end_minute))
    merged: list[tuple[int, int, int]] = []
    for interval in unique:
        day = int(interval.day)
        if merged and merged[-1][0] == day and interval.start_minute <= merged[-1][2]:
            previous = merged[-1]
            merged[-1] = (day, previous[1], max(previous[2], interval.end_minute))
        else:
            merged.append((day, interval.start_minute, interval.end_minute))
    session_keys = {
        (int(item.day), item.session_id)
        if item.session_id
        else (int(item.day), f"{item.start_minute}-{item.end_minute}")
        for item in unique
    }
    return Workload(
        weekly_minutes=sum(end - start for _, start, end in merged),
        meeting_count=len(unique),
        session_count=len(session_keys),
    )
