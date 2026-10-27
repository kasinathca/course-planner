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
    migration = root.joinpath("0001_initial.sql")
    return (Migration(1, "initial", migration.read_text(encoding="utf-8")),)
