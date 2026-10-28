from __future__ import annotations

import json
from pathlib import Path

import pytest

from ffcs_studio.persistence.database import Database
from ffcs_studio.persistence.migrations import packaged_migrations
from ffcs_studio.persistence.scenario_repository import (
    ScenarioRepository,
    ScenarioRevisionConflict,
)


def draft_document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "campus": "Vellore",
        "semester_label": "",
        "calendar_id": None,
        "mode": "exploratory",
        "courses": [],
        "occupied_intervals": [],
        "credit_constraints": {},
        "ranking": {},
        "provisional_policy": {},
        "top_k": 20,
        "max_search_nodes": 2000000,
    }


def test_migration_0003_preserves_v2_data_and_creates_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    migrations = packaged_migrations()
    assert database.initialize(migrations[:2]) == 2
    with database.transaction() as connection:
        connection.execute("UPDATE app_state SET data_revision = 7 WHERE singleton_id = 1")
    assert database.initialize() == 3
    with database.connection() as connection:
        assert (
            connection.execute(
                "SELECT data_revision FROM app_state WHERE singleton_id = 1"
            ).fetchone()[0]
            == 7
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"saved_scenarios", "scenario_revisions", "saved_timetable_results"} <= tables
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert list(database.backup_dir.glob("*.sqlite3"))


def test_scenario_revision_lifecycle_and_restart(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    assert database.initialize() == 3
    repository = ScenarioRepository(database)
    created = repository.create(
        name="First plan",
        description="incomplete but structurally valid",
        document=draft_document(),
        source_references={"calendar_id": None, "offerings": []},
        status="draft",
    )
    scenario_id = str(created["scenario_id"])
    assert created["current_revision"] == 1
    assert created["document"]["courses"] == []

    changed_document = draft_document()
    changed_document["semester_label"] = "Fall Semester 2026-27"
    updated = repository.update(
        scenario_id,
        expected_revision=1,
        name="Renamed plan",
        description="reviewed later",
        document=changed_document,
        source_references={"calendar_id": None, "offerings": []},
        status="draft",
        change_summary="Set semester",
    )
    assert updated["current_revision"] == 2
    assert [item["revision"] for item in repository.revisions(scenario_id)] == [2, 1]
    with pytest.raises(ScenarioRevisionConflict):
        repository.update(
            scenario_id,
            expected_revision=1,
            name="stale overwrite",
            description="",
            document=changed_document,
            source_references={},
            status="draft",
            change_summary="must fail",
        )

    restored = repository.restore_revision(scenario_id, source_revision=1, expected_revision=2)
    assert restored["current_revision"] == 3
    assert restored["document"]["semester_label"] == ""
    duplicated = repository.duplicate(scenario_id, name="Copy")
    assert duplicated["scenario_id"] != scenario_id
    assert duplicated["current_revision"] == 1

    archived = repository.archive(scenario_id, expected_revision=3)
    assert archived["status"] == "archived"
    assert repository.list(page=1, page_size=20)["total"] == 1
    assert repository.list(page=1, page_size=20, include_archived=True)["total"] == 2
    unarchived = repository.unarchive(scenario_id)
    assert unarchived["status"] == "draft"

    restarted = ScenarioRepository(Database(database.path))
    assert restarted.get(scenario_id)["current_revision"] == 3
    assert json.dumps(restarted.get(scenario_id)["document"], sort_keys=True)

    restarted.delete(str(duplicated["scenario_id"]), expected_revision=1)
    assert restarted.list(page=1, page_size=20, include_archived=True)["total"] == 1
