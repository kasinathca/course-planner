"""Revision-safe SQLite storage for planning scenarios and timetable snapshots."""

from __future__ import annotations

import builtins
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ffcs_studio.persistence.database import Database


class ScenarioRepositoryError(RuntimeError):
    code = "scenario_repository_error"


class ScenarioNotFound(ScenarioRepositoryError):
    code = "scenario_not_found"


class ScenarioRevisionConflict(ScenarioRepositoryError):
    code = "scenario_revision_conflict"


class SavedResultNotFound(ScenarioRepositoryError):
    code = "saved_result_not_found"


class ScenarioRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        name: str,
        description: str,
        document: dict[str, Any],
        source_references: dict[str, Any],
        status: str,
        change_summary: str = "Scenario created",
    ) -> dict[str, Any]:
        scenario_id = uuid4().hex
        now = _now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO saved_scenarios(scenario_id, name, description, campus, "
                "semester_label, calendar_id, document_schema_version, current_revision, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, '1.0', 1, ?, ?, ?)",
                (
                    scenario_id,
                    name,
                    description,
                    str(document.get("campus", "")),
                    str(document.get("semester_label", "")),
                    document.get("calendar_id") or None,
                    status,
                    now,
                    now,
                ),
            )
            self._insert_revision(
                connection,
                scenario_id,
                1,
                document,
                source_references,
                status,
                change_summary,
                now,
            )
        return self.get(scenario_id)

    def list(self, *, page: int, page_size: int, include_archived: bool = False) -> dict[str, Any]:
        where = "1 = 1" if include_archived else "archived_at IS NULL"
        offset = (page - 1) * page_size
        with self.database.connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM saved_scenarios WHERE {where}"
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM saved_timetable_results r "
                "WHERE r.scenario_id = s.scenario_id) AS saved_result_count, "
                "(SELECT r.saved_result_id FROM saved_timetable_results r "
                "WHERE r.scenario_id = s.scenario_id AND r.is_preferred = 1) "
                f"AS preferred_result_id FROM saved_scenarios s WHERE {where} "
                "ORDER BY s.updated_at DESC, s.scenario_id LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def get(self, scenario_id: str, *, revision: int | None = None) -> dict[str, Any]:
        with self.database.connection() as connection:
            scenario = connection.execute(
                "SELECT * FROM saved_scenarios WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()
            if scenario is None:
                raise ScenarioNotFound("Saved scenario was not found")
            selected_revision = revision or int(scenario["current_revision"])
            stored = connection.execute(
                "SELECT * FROM scenario_revisions WHERE scenario_id = ? AND revision = ?",
                (scenario_id, selected_revision),
            ).fetchone()
            if stored is None:
                raise ScenarioNotFound("Saved scenario revision was not found")
        result = dict(scenario)
        result.update(
            {
                "revision": selected_revision,
                "document": json.loads(stored["document_json"]),
                "source_references": json.loads(stored["source_references_json"]),
                "revision_status": stored["status"],
                "change_summary": stored["change_summary"],
                "revision_created_at": stored["created_at"],
            }
        )
        return result

    def update(
        self,
        scenario_id: str,
        *,
        expected_revision: int,
        name: str,
        description: str,
        document: dict[str, Any],
        source_references: dict[str, Any],
        status: str,
        change_summary: str,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT current_revision, archived_at FROM saved_scenarios WHERE scenario_id = ?",
                (scenario_id,),
            ).fetchone()
            if row is None:
                raise ScenarioNotFound("Saved scenario was not found")
            if int(row["current_revision"]) != expected_revision:
                raise ScenarioRevisionConflict(
                    "The scenario changed after it was opened; reload before saving"
                )
            if row["archived_at"] is not None:
                raise ScenarioRepositoryError("Archived scenarios must be restored before editing")
            revision = expected_revision + 1
            self._insert_revision(
                connection,
                scenario_id,
                revision,
                document,
                source_references,
                status,
                change_summary,
                now,
            )
            changed = connection.execute(
                "UPDATE saved_scenarios SET name = ?, description = ?, campus = ?, "
                "semester_label = ?, calendar_id = ?, current_revision = ?, status = ?, "
                "updated_at = ? WHERE scenario_id = ? AND current_revision = ?",
                (
                    name,
                    description,
                    str(document.get("campus", "")),
                    str(document.get("semester_label", "")),
                    document.get("calendar_id") or None,
                    revision,
                    status,
                    now,
                    scenario_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise ScenarioRevisionConflict("Concurrent scenario update was rejected")
        return self.get(scenario_id)

    def duplicate(self, scenario_id: str, *, name: str) -> dict[str, Any]:
        source = self.get(scenario_id)
        return self.create(
            name=name,
            description=str(source["description"]),
            document=source["document"],
            source_references=source["source_references"],
            status="draft" if source["revision_status"] == "stale" else source["revision_status"],
            change_summary=f"Duplicated from {scenario_id}",
        )

    def revisions(self, scenario_id: str) -> builtins.list[dict[str, Any]]:
        self.get(scenario_id)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT revision, status, change_summary, created_at FROM scenario_revisions "
                "WHERE scenario_id = ? ORDER BY revision DESC",
                (scenario_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_revision(
        self, scenario_id: str, *, source_revision: int, expected_revision: int
    ) -> dict[str, Any]:
        current = self.get(scenario_id)
        if int(current["current_revision"]) != expected_revision:
            raise ScenarioRevisionConflict(
                "The scenario changed after it was opened; reload before restoring"
            )
        historical = self.get(scenario_id, revision=source_revision)
        return self.update(
            scenario_id,
            expected_revision=expected_revision,
            name=str(current["name"]),
            description=str(current["description"]),
            document=historical["document"],
            source_references=historical["source_references"],
            status=str(historical["revision_status"]),
            change_summary=f"Restored revision {source_revision}",
        )

    def archive(self, scenario_id: str, *, expected_revision: int) -> dict[str, Any]:
        now = _now()
        with self.database.transaction() as connection:
            changed = connection.execute(
                "UPDATE saved_scenarios SET status = 'archived', archived_at = ?, updated_at = ? "
                "WHERE scenario_id = ? AND current_revision = ? AND archived_at IS NULL",
                (now, now, scenario_id, expected_revision),
            ).rowcount
            if changed != 1:
                if (
                    connection.execute(
                        "SELECT 1 FROM saved_scenarios WHERE scenario_id = ?", (scenario_id,)
                    ).fetchone()
                    is None
                ):
                    raise ScenarioNotFound("Saved scenario was not found")
                raise ScenarioRevisionConflict("Scenario revision changed before archive")
        return self.get(scenario_id)

    def unarchive(self, scenario_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT current_revision FROM saved_scenarios WHERE scenario_id = ?",
                (scenario_id,),
            ).fetchone()
            if row is None:
                raise ScenarioNotFound("Saved scenario was not found")
            revision = connection.execute(
                "SELECT status FROM scenario_revisions WHERE scenario_id = ? AND revision = ?",
                (scenario_id, row["current_revision"]),
            ).fetchone()
            connection.execute(
                "UPDATE saved_scenarios SET status = ?, archived_at = NULL, updated_at = ? "
                "WHERE scenario_id = ?",
                (revision["status"], _now(), scenario_id),
            )
        return self.get(scenario_id)

    def delete(self, scenario_id: str, *, expected_revision: int) -> None:
        with self.database.transaction() as connection:
            changed = connection.execute(
                "DELETE FROM saved_scenarios WHERE scenario_id = ? AND current_revision = ?",
                (scenario_id, expected_revision),
            ).rowcount
            if changed != 1:
                if (
                    connection.execute(
                        "SELECT 1 FROM saved_scenarios WHERE scenario_id = ?", (scenario_id,)
                    ).fetchone()
                    is None
                ):
                    raise ScenarioNotFound("Saved scenario was not found")
                raise ScenarioRevisionConflict("Scenario revision changed before deletion")

    def save_result(
        self,
        *,
        scenario_id: str,
        scenario_revision: int,
        name: str,
        solver_result_id: str,
        solver_fingerprint: str,
        calendar_id: str,
        result: dict[str, Any],
        source_references: dict[str, Any],
        verification_status: str,
    ) -> dict[str, Any]:
        saved_result_id = uuid4().hex
        with self.database.transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM scenario_revisions WHERE scenario_id = ? AND revision = ?",
                    (scenario_id, scenario_revision),
                ).fetchone()
                is None
            ):
                raise ScenarioNotFound("Scenario revision was not found")
            connection.execute(
                "INSERT INTO saved_timetable_results(saved_result_id, scenario_id, "
                "scenario_revision, name, solver_result_id, solver_fingerprint, calendar_id, "
                "snapshot_schema_version, result_json, source_references_json, "
                "verification_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '1.0', ?, ?, ?, ?)",
                (
                    saved_result_id,
                    scenario_id,
                    scenario_revision,
                    name,
                    solver_result_id,
                    solver_fingerprint,
                    calendar_id,
                    _canonical(result),
                    _canonical(source_references),
                    verification_status,
                    _now(),
                ),
            )
        return self.get_result(saved_result_id)

    def list_results(self, scenario_id: str, *, page: int, page_size: int) -> dict[str, Any]:
        self.get(scenario_id)
        offset = (page - 1) * page_size
        with self.database.connection() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM saved_timetable_results WHERE scenario_id = ?",
                    (scenario_id,),
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT saved_result_id, scenario_id, scenario_revision, name, "
                "solver_result_id, solver_fingerprint, calendar_id, verification_status, "
                "is_preferred, created_at FROM saved_timetable_results WHERE scenario_id = ? "
                "ORDER BY created_at DESC, saved_result_id LIMIT ? OFFSET ?",
                (scenario_id, page_size, offset),
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def get_result(self, saved_result_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM saved_timetable_results WHERE saved_result_id = ?",
                (saved_result_id,),
            ).fetchone()
        if row is None:
            raise SavedResultNotFound("Saved timetable result was not found")
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["source_references"] = json.loads(result.pop("source_references_json"))
        return result

    def prefer_result(self, saved_result_id: str) -> dict[str, Any]:
        result = self.get_result(saved_result_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE saved_timetable_results SET is_preferred = 0 WHERE scenario_id = ?",
                (result["scenario_id"],),
            )
            connection.execute(
                "UPDATE saved_timetable_results SET is_preferred = 1 WHERE saved_result_id = ?",
                (saved_result_id,),
            )
        return self.get_result(saved_result_id)

    @staticmethod
    def _insert_revision(
        connection: Any,
        scenario_id: str,
        revision: int,
        document: dict[str, Any],
        source_references: dict[str, Any],
        status: str,
        change_summary: str,
        created_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO scenario_revisions(scenario_id, revision, document_json, "
            "source_references_json, status, change_summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                scenario_id,
                revision,
                _canonical(document),
                _canonical(source_references),
                status,
                change_summary,
                created_at,
            ),
        )


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()
