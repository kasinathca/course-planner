"""Versioned SQLite migration loading."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def packaged_migrations() -> tuple[Migration, ...]:
    root = resources.files("ffcs_studio.persistence.schema")
    initial = root.joinpath("0001_initial.sql")
    calendars = root.joinpath("0002_slot_calendars.sql")
    scenarios = root.joinpath("0003_saved_scenarios.sql")
    degree = root.joinpath("0004_degree_planning.sql")
    return (
        Migration(1, "initial", initial.read_text(encoding="utf-8")),
        Migration(2, "slot-calendars-and-component-rules", calendars.read_text(encoding="utf-8")),
        Migration(3, "saved-scenarios-and-results", scenarios.read_text(encoding="utf-8")),
        Migration(4, "degree-planning-and-recovery", degree.read_text(encoding="utf-8")),
    )
