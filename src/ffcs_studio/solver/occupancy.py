"""Exact weekly minute occupancy masks and independent interval helpers."""

from __future__ import annotations

from collections.abc import Iterable

from ffcs_studio.solver.models import SolverInterval

MINUTES_PER_DAY = 1440


def interval_mask(interval: SolverInterval) -> int:
    """Return an exact half-open minute bitset for one weekly interval."""

    offset = interval.day * MINUTES_PER_DAY + interval.start_minute
    length = interval.end_minute - interval.start_minute
    return ((1 << length) - 1) << offset


def occupancy_mask(intervals: Iterable[SolverInterval]) -> int:
    mask = 0
    for interval in intervals:
        mask |= interval_mask(interval)
    return mask


def intervals_conflict(intervals: Iterable[SolverInterval]) -> bool:
    ordered = tuple(intervals)
    return any(
        left.overlaps(right)
        for index, left in enumerate(ordered)
        for right in ordered[index + 1 :]
        if left.allocation_id != right.allocation_id
    )


def masks_match_interval_overlap(
    left: SolverInterval,
    right: SolverInterval,
) -> bool:
    return bool(interval_mask(left) & interval_mask(right)) == left.overlaps(right)
