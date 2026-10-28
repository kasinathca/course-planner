"""SQLite persistence for curricula, degree timelines and recovery evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ffcs_studio.degree.models import PROGRAMME_POLICY_2024, ProgrammePolicy
from ffcs_studio.persistence.database import Database


class DegreeRepositoryError(RuntimeError):
    code = "degree_repository_error"


class DegreeNotFound(DegreeRepositoryError):
    code = "degree_not_found"


class DegreeRevisionConflict(DegreeRepositoryError):
    code = "degree_revision_conflict"


class DegreeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_programme(self, policy: ProgrammePolicy = PROGRAMME_POLICY_2024) -> dict[str, Any]:
        programme_id = policy.programme_code.lower()
        source = {"policy": "recorded-programme-targets", "revision": policy.revision_code}
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO programmes(programme_id, programme_code, name, admission_batch, provenance, created_at) VALUES (?, ?, ?, ?, 'user_supplied_curriculum', ?)",
                (programme_id, policy.programme_code, policy.name, policy.admission_batch, _now()),
            )
            existing = connection.execute(
                "SELECT curriculum_id FROM curriculum_revisions WHERE programme_id = ? AND revision_code = ? ORDER BY created_at LIMIT 1",
                (programme_id, policy.revision_code),
            ).fetchone()
            if existing is None:
                curriculum_id = f"{programme_id}-{policy.revision_code}"
                connection.execute(
                    "INSERT INTO curriculum_revisions(curriculum_id, programme_id, revision_code, name, status, displayed_total_milli, nc_accounting_status, source_digest, source_json, created_at) VALUES (?, ?, ?, ?, 'active', ?, 'pending_classification', 'recorded-policy', ?, ?)",
                    (
                        curriculum_id,
                        programme_id,
                        policy.revision_code,
                        f"{policy.name} {policy.revision_code}",
                        policy.displayed_total_milli,
                        _json(source),
                        _now(),
                    ),
                )
                for category in policy.categories:
                    connection.execute(
                        "INSERT INTO programme_category_requirements(curriculum_id, category_code, category_name, recorded_target_milli, confirmed_credit_target_milli, non_credit_target_units, counted_in_graduation, surplus_allowed, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            curriculum_id,
                            category.code,
                            category.name,
                            category.recorded_target_milli,
                            category.confirmed_credit_target_milli,
                            category.non_credit_target_units,
                            _optional_bool(category.counted_in_graduation),
                            int(category.surplus_allowed),
                            category.notes,
                        ),
                    )
            else:
                curriculum_id = str(existing["curriculum_id"])
        return self.get_curriculum(curriculum_id)

    def list_programmes(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT p.*, COUNT(c.curriculum_id) AS curriculum_count FROM programmes p LEFT JOIN curriculum_revisions c ON c.programme_id = p.programme_id GROUP BY p.programme_id ORDER BY p.name"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_curricula(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT c.*, p.programme_code, p.admission_batch, COUNT(cc.catalogue_course_id) AS course_count FROM curriculum_revisions c JOIN programmes p ON p.programme_id = c.programme_id LEFT JOIN catalogue_courses cc ON cc.curriculum_id = c.curriculum_id GROUP BY c.curriculum_id ORDER BY c.created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_curriculum(self, curriculum_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT c.*, p.programme_code, p.name AS programme_name, p.admission_batch FROM curriculum_revisions c JOIN programmes p ON p.programme_id = c.programme_id WHERE c.curriculum_id = ?",
                (curriculum_id,),
            ).fetchone()
            if row is None:
                raise DegreeNotFound("Curriculum was not found")
            categories = connection.execute(
                "SELECT * FROM programme_category_requirements WHERE curriculum_id = ? ORDER BY rowid",
                (curriculum_id,),
            ).fetchall()
        result = dict(row)
        result["categories"] = [dict(item) for item in categories]
        return result

    def commit_curriculum(self, parsed: dict[str, Any], *, filename: str) -> dict[str, Any]:
        programme = parsed["programme"]
        programme_id = str(programme["programme_code"]).lower()
        curriculum_id = f"curr-{uuid4().hex}"
        import_id = f"cimp-{uuid4().hex}"
        with self.database.connection() as connection:
            duplicate = connection.execute(
                "SELECT curriculum_import_id, curriculum_id FROM curriculum_import_snapshots WHERE source_digest = ?",
                (parsed["digest"],),
            ).fetchone()
        if duplicate is not None:
            return {
                "duplicate": True,
                "curriculum_import_id": duplicate["curriculum_import_id"],
                "curriculum_id": duplicate["curriculum_id"],
            }
        self.database.create_backup("pre-degree-import")
        with self.database.transaction() as connection:
            duplicate = connection.execute(
                "SELECT curriculum_import_id, curriculum_id FROM curriculum_import_snapshots WHERE source_digest = ?",
                (parsed["digest"],),
            ).fetchone()
            if duplicate is not None:
                return {
                    "duplicate": True,
                    "curriculum_import_id": duplicate["curriculum_import_id"],
                    "curriculum_id": duplicate["curriculum_id"],
                }
            connection.execute(
                "INSERT OR IGNORE INTO programmes(programme_id, programme_code, name, admission_batch, provenance, created_at) VALUES (?, ?, ?, ?, 'user_supplied_curriculum', ?)",
                (
                    programme_id,
                    programme["programme_code"],
                    programme["name"],
                    programme["admission_batch"],
                    _now(),
                ),
            )
            displayed_total = int(programme.get("displayed_total_milli", 0))
            connection.execute(
                "INSERT INTO curriculum_revisions(curriculum_id, programme_id, revision_code, name, status, displayed_total_milli, nc_accounting_status, source_digest, source_json, created_at) VALUES (?, ?, ?, ?, 'reviewed', ?, ?, ?, ?, ?)",
                (
                    curriculum_id,
                    programme_id,
                    programme["revision_code"],
                    str(programme.get("revision_name") or programme["revision_code"]),
                    displayed_total,
                    str(programme.get("nc_accounting_status") or "pending_classification"),
                    parsed["digest"],
                    _json(parsed["raw"]),
                    _now(),
                ),
            )
            for category in programme.get("categories", []):
                connection.execute(
                    "INSERT INTO programme_category_requirements(curriculum_id, category_code, category_name, recorded_target_milli, confirmed_credit_target_milli, non_credit_target_units, counted_in_graduation, surplus_allowed, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        curriculum_id,
                        category["code"],
                        category.get("name", category["code"]),
                        int(category.get("recorded_target_milli", 0)),
                        category.get("confirmed_credit_target_milli"),
                        int(category.get("non_credit_target_units", 0)),
                        _optional_bool(category.get("counted_in_graduation")),
                        int(bool(category.get("surplus_allowed", True))),
                        str(category.get("notes", "")),
                    ),
                )
            course_identity_map = {
                course["canonical_id"]: f"{curriculum_id}:{course['canonical_id']}"
                for course in parsed["courses"]
            }
            for index, course in enumerate(parsed["courses"]):
                connection.execute(
                    "INSERT INTO catalogue_courses(catalogue_course_id, curriculum_id, canonical_identity, source_identity, source_order, course_code, course_title, category_code, curriculum_type, lecture, tutorial, practical, project, total_credits_milli, provenance, alternative_group, notes, unresolved_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        course_identity_map[course["canonical_id"]],
                        curriculum_id,
                        course["canonical_id"],
                        course["source_id"],
                        index,
                        course["code"],
                        course["title"],
                        course["category"],
                        course["curriculum_type"],
                        course["lecture"],
                        course["tutorial"],
                        course["practical"],
                        course["project"],
                        course["total_credits_milli"],
                        course["provenance"],
                        course["alternative_group"],
                        course["notes"],
                        _json(course["unresolved"]),
                    ),
                )
            for relationship in parsed.get("relationships", []):
                source_relationship_id = str(relationship.get("relationship_id") or uuid4().hex)
                source_course_ids = [str(item) for item in relationship.get("course_ids", [])]
                unknown_ids = [
                    course_id
                    for course_id in source_course_ids
                    if course_id not in course_identity_map
                ]
                if unknown_ids:
                    raise DegreeRepositoryError(
                        "Course relationship references unknown canonical identities: "
                        + ", ".join(unknown_ids)
                    )
                connection.execute(
                    "INSERT INTO course_relationships(relationship_id, curriculum_id, source_identity, relationship_type, requirement_key, verified, provenance, notes, course_ids_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{curriculum_id}:{source_relationship_id}",
                        curriculum_id,
                        source_relationship_id,
                        relationship["relationship_type"],
                        relationship.get("requirement_key"),
                        int(bool(relationship.get("verified", False))),
                        str(relationship.get("provenance", "user_supplied")),
                        str(relationship.get("notes", "")),
                        _json([course_identity_map[item] for item in source_course_ids]),
                    ),
                )
            for rule in parsed.get("prerequisites", []):
                source_rule_id = str(rule.get("rule_id") or uuid4().hex)
                rule_id = f"{curriculum_id}:{source_rule_id}"
                source_course_id = str(rule["course_id"])
                if source_course_id not in course_identity_map:
                    raise DegreeRepositoryError(
                        f"Prerequisite rule {rule_id} references unknown course {source_course_id}"
                    )
                all_of = [str(item) for item in rule.get("all_of", [])]
                any_of = [
                    [str(item) for item in group]
                    for group in rule.get("any_of", [])
                    if isinstance(group, list)
                ]
                unknown_ids = [
                    course_id
                    for course_id in (*all_of, *(item for group in any_of for item in group))
                    if course_id not in course_identity_map
                ]
                if unknown_ids:
                    raise DegreeRepositoryError(
                        f"Prerequisite rule {rule_id} references unknown requirements: "
                        + ", ".join(unknown_ids)
                    )
                connection.execute(
                    "INSERT INTO prerequisite_rules(prerequisite_rule_id, curriculum_id, "
                    "source_identity, catalogue_course_id, all_of_json, any_of_json, "
                    "minimum_semester, verified, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rule_id,
                        curriculum_id,
                        source_rule_id,
                        course_identity_map[source_course_id],
                        _json([course_identity_map[item] for item in all_of]),
                        _json([[course_identity_map[item] for item in group] for group in any_of]),
                        rule.get("minimum_semester"),
                        int(bool(rule.get("verified", False))),
                        str(rule.get("provenance", "user_supplied")),
                    ),
                )
            connection.execute(
                "INSERT INTO curriculum_import_snapshots(curriculum_import_id, curriculum_id, import_kind, original_filename, source_digest, raw_json, preview_json, committed_at) VALUES (?, ?, 'canonical', ?, ?, ?, ?, ?)",
                (
                    import_id,
                    curriculum_id,
                    filename,
                    parsed["digest"],
                    _json(parsed["raw"]),
                    _json({key: value for key, value in parsed.items() if key != "raw"}),
                    _now(),
                ),
            )
        return {
            "duplicate": False,
            "curriculum_import_id": import_id,
            "curriculum_id": curriculum_id,
        }

    def commit_legacy(self, parsed: dict[str, Any]) -> dict[str, Any]:
        import_id = f"limp-{uuid4().hex}"
        with self.database.connection() as connection:
            duplicate = connection.execute(
                "SELECT curriculum_import_id FROM curriculum_import_snapshots WHERE source_digest = ?",
                (parsed["snapshot_id"],),
            ).fetchone()
        if duplicate is not None:
            return {
                "duplicate": True,
                "curriculum_import_id": duplicate["curriculum_import_id"],
            }
        self.database.create_backup("pre-degree-import")
        with self.database.transaction() as connection:
            duplicate = connection.execute(
                "SELECT curriculum_import_id FROM curriculum_import_snapshots WHERE source_digest = ?",
                (parsed["snapshot_id"],),
            ).fetchone()
            if duplicate is not None:
                return {
                    "duplicate": True,
                    "curriculum_import_id": duplicate["curriculum_import_id"],
                }
            connection.execute(
                "INSERT INTO curriculum_import_snapshots(curriculum_import_id, curriculum_id, import_kind, original_filename, source_sequence, source_digest, source_updated_at, raw_json, preview_json, committed_at) VALUES (?, NULL, 'legacy_v6', ?, ?, ?, ?, ?, ?, ?)",
                (
                    import_id,
                    parsed["source_name"],
                    parsed["source_sequence"],
                    parsed["snapshot_id"],
                    parsed["updated_at"],
                    _json(parsed["raw"]),
                    _json({key: value for key, value in parsed.items() if key != "raw"}),
                    _now(),
                ),
            )
        return {
            "duplicate": False,
            "curriculum_import_id": import_id,
            "snapshot_id": parsed["snapshot_id"],
        }

    def list_legacy_imports(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT curriculum_import_id, original_filename, source_sequence, source_digest AS snapshot_id, source_updated_at, preview_json, committed_at FROM curriculum_import_snapshots WHERE import_kind = 'legacy_v6' ORDER BY source_sequence, committed_at"
            ).fetchall()
        return [{**dict(row), "preview": json.loads(row["preview_json"])} for row in rows]

    def legacy_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT curriculum_import_id, original_filename, source_sequence, "
                "source_digest AS snapshot_id, source_updated_at, preview_json, committed_at "
                "FROM curriculum_import_snapshots "
                "WHERE import_kind = 'legacy_v6' AND source_digest = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise DegreeNotFound("Legacy snapshot was not found")
        return {**dict(row), "preview": json.loads(row["preview_json"])}

    def list_catalogue(
        self,
        curriculum_id: str,
        *,
        query: str = "",
        category: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        filters = ["curriculum_id = ?"]
        parameters: list[Any] = [curriculum_id]
        if query:
            filters.append("(lower(course_code) LIKE ? OR lower(course_title) LIKE ?)")
            term = f"%{query.casefold()}%"
            parameters.extend((term, term))
        if category:
            filters.append("category_code = ?")
            parameters.append(category)
        where = " AND ".join(filters)
        offset = (page - 1) * page_size
        with self.database.connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM catalogue_courses WHERE {where}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM catalogue_courses WHERE {where} ORDER BY course_code, source_order LIMIT ? OFFSET ?",
                (*parameters, page_size, offset),
            ).fetchall()
        return {
            "items": [_course_row(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def get_catalogue_course(self, catalogue_course_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM catalogue_courses WHERE catalogue_course_id = ?",
                (catalogue_course_id,),
            ).fetchone()
        if row is None:
            raise DegreeNotFound("Catalogue course was not found")
        return _course_row(row)

    def create_plan(
        self,
        *,
        name: str,
        curriculum_id: str,
        document: dict[str, Any],
        source_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        curriculum = self.get_curriculum(curriculum_id)
        plan_id = f"plan-{uuid4().hex}"
        now = _now()
        with self.database.transaction() as connection:
            normalized_document = self._normalize_plan_document(connection, curriculum_id, document)
            connection.execute(
                "INSERT INTO degree_plans(degree_plan_id, name, programme_id, curriculum_id, current_revision, status, created_at, updated_at) VALUES (?, ?, ?, ?, 1, 'active', ?, ?)",
                (plan_id, name, curriculum["programme_id"], curriculum_id, now, now),
            )
            self._insert_plan_revision(
                connection,
                plan_id,
                1,
                normalized_document,
                "Plan created",
                source_snapshot_id,
                now,
            )
        return self.get_plan(plan_id)

    def normalize_plan_document(
        self, curriculum_id: str, document: dict[str, Any]
    ) -> dict[str, Any]:
        with self.database.connection() as connection:
            return self._normalize_plan_document(connection, curriculum_id, document)

    def update_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
        name: str,
        document: dict[str, Any],
        change_summary: str,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT current_revision, archived_at, curriculum_id FROM degree_plans WHERE degree_plan_id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise DegreeNotFound("Degree plan was not found")
            if int(row["current_revision"]) != expected_revision:
                raise DegreeRevisionConflict("Degree plan changed after it was opened")
            if row["archived_at"] is not None:
                raise DegreeRepositoryError("Archived degree plans cannot be edited")
            revision = expected_revision + 1
            normalized_document = self._normalize_plan_document(
                connection, str(row["curriculum_id"]), document
            )
            self._insert_plan_revision(
                connection, plan_id, revision, normalized_document, change_summary, None, now
            )
            changed = connection.execute(
                "UPDATE degree_plans SET name = ?, current_revision = ?, updated_at = ? WHERE degree_plan_id = ? AND current_revision = ?",
                (name, revision, now, plan_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise DegreeRevisionConflict("Concurrent degree-plan update was rejected")
        return self.get_plan(plan_id)

    def get_plan(self, plan_id: str, *, revision: int | None = None) -> dict[str, Any]:
        with self.database.connection() as connection:
            plan = connection.execute(
                "SELECT * FROM degree_plans WHERE degree_plan_id = ?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise DegreeNotFound("Degree plan was not found")
            selected = revision or int(plan["current_revision"])
            stored = connection.execute(
                "SELECT * FROM degree_plan_revisions WHERE degree_plan_id = ? AND revision = ?",
                (plan_id, selected),
            ).fetchone()
            if stored is None:
                raise DegreeNotFound("Degree-plan revision was not found")
        result = dict(plan)
        result.update(
            {
                "revision": selected,
                "document": json.loads(stored["document_json"]),
                "change_summary": stored["change_summary"],
                "revision_created_at": stored["created_at"],
                "source_snapshot_id": stored["source_snapshot_id"],
            }
        )
        return result

    def list_plans(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "1 = 1" if include_archived else "archived_at IS NULL"
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM degree_plans WHERE {where} ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def revisions(self, plan_id: str) -> list[dict[str, Any]]:
        self.get_plan(plan_id)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT revision, change_summary, source_snapshot_id, created_at FROM degree_plan_revisions WHERE degree_plan_id = ? ORDER BY revision DESC",
                (plan_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_plan(
        self, plan_id: str, *, source_revision: int, expected_revision: int
    ) -> dict[str, Any]:
        historical = self.get_plan(plan_id, revision=source_revision)
        current = self.get_plan(plan_id)
        if int(current["current_revision"]) != expected_revision:
            raise DegreeRevisionConflict("Degree plan changed before restore")
        return self.update_plan(
            plan_id,
            expected_revision=expected_revision,
            name=str(current["name"]),
            document=historical["document"],
            change_summary=f"Restored revision {source_revision}",
        )

    def duplicate_plan(self, plan_id: str, *, name: str) -> dict[str, Any]:
        source = self.get_plan(plan_id)
        return self.create_plan(
            name=name, curriculum_id=str(source["curriculum_id"]), document=source["document"]
        )

    def archive_plan(self, plan_id: str, *, expected_revision: int) -> dict[str, Any]:
        now = _now()
        with self.database.transaction() as connection:
            changed = connection.execute(
                "UPDATE degree_plans SET status = 'archived', archived_at = ?, updated_at = ? WHERE degree_plan_id = ? AND current_revision = ? AND archived_at IS NULL",
                (now, now, plan_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise DegreeRevisionConflict("Degree plan revision changed before archive")
        return self.get_plan(plan_id)

    def compare_plans(
        self, plan_id: str, left_revision: int, right_revision: int
    ) -> dict[str, Any]:
        left = self.get_plan(plan_id, revision=left_revision)["document"]
        right = self.get_plan(plan_id, revision=right_revision)["document"]
        before = {row["record_id"]: row for row in left.get("records", [])}
        after = {row["record_id"]: row for row in right.get("records", [])}
        return {
            "left_revision": left_revision,
            "right_revision": right_revision,
            "added": [after[key] for key in sorted(after.keys() - before.keys())],
            "removed": [before[key] for key in sorted(before.keys() - after.keys())],
            "changed": [
                {"before": before[key], "after": after[key]}
                for key in sorted(before.keys() & after.keys())
                if before[key] != after[key]
            ],
        }

    def set_availability(
        self,
        *,
        campus: str,
        semester_label: str,
        offering_revision_id: int,
        allocation_id: int,
        state: str,
        provenance: str,
        note: str,
        captured_at: str,
    ) -> dict[str, Any]:
        availability_id = f"avail-{uuid4().hex}"
        with self.database.transaction() as connection:
            match = connection.execute(
                "SELECT 1 FROM allocation_rows WHERE allocation_id = ? AND revision_id = ?",
                (allocation_id, offering_revision_id),
            ).fetchone()
            if match is None:
                raise DegreeRepositoryError(
                    "Allocation does not belong to the selected offering revision"
                )
            connection.execute(
                "UPDATE registration_availability_history SET cleared_at = ? "
                "WHERE offering_revision_id = ? AND allocation_id = ? AND cleared_at IS NULL",
                (captured_at, offering_revision_id, allocation_id),
            )
            connection.execute(
                "INSERT INTO registration_availability_history(availability_id, campus, semester_label, offering_revision_id, allocation_id, state, provenance, note, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    availability_id,
                    campus,
                    semester_label,
                    offering_revision_id,
                    allocation_id,
                    state,
                    provenance,
                    note,
                    captured_at,
                ),
            )
        return self.get_availability(availability_id)

    def get_availability(self, availability_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM registration_availability_history WHERE availability_id = ?",
                (availability_id,),
            ).fetchone()
        if row is None:
            raise DegreeNotFound("Availability record was not found")
        return dict(row)

    def list_availability(
        self, *, campus: str = "", semester_label: str = ""
    ) -> list[dict[str, Any]]:
        filters = ["cleared_at IS NULL"]
        values: list[Any] = []
        if campus:
            filters.append("campus = ?")
            values.append(campus)
        if semester_label:
            filters.append("semester_label = ?")
            values.append(semester_label)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM registration_availability_history WHERE {' AND '.join(filters)} ORDER BY captured_at DESC",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_availability(self, availability_id: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            changed = connection.execute(
                "UPDATE registration_availability_history SET cleared_at = ? WHERE availability_id = ? AND cleared_at IS NULL",
                (_now(), availability_id),
            ).rowcount
            if changed != 1:
                raise DegreeNotFound("Active availability record was not found")
        return self.get_availability(availability_id)

    def save_recovery(
        self,
        *,
        request: dict[str, Any],
        result: dict[str, Any],
        scenario_id: str | None,
        scenario_revision: int | None,
        fingerprint: str,
    ) -> dict[str, Any]:
        run_id = f"recover-{uuid4().hex}"
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO recovery_runs(recovery_run_id, scenario_id, scenario_revision, source_revision_fingerprint, request_json, result_json, status, proven_minimum, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    scenario_id,
                    scenario_revision,
                    fingerprint,
                    _json(request),
                    _json(result),
                    result["status"],
                    int(bool(result.get("proven_minimum"))),
                    _now(),
                ),
            )
        return {"recovery_run_id": run_id, **result}

    def _insert_plan_revision(
        self,
        connection: Any,
        plan_id: str,
        revision: int,
        document: dict[str, Any],
        change_summary: str,
        source_snapshot_id: str | None,
        created_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO degree_plan_revisions(degree_plan_id, revision, document_json, change_summary, source_snapshot_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (plan_id, revision, _json(document), change_summary, source_snapshot_id, created_at),
        )
        for row in document.get("records", []):
            connection.execute(
                "INSERT INTO degree_plan_entries(degree_plan_id, revision, record_id, catalogue_course_id, semester_number, status, intended_category, attempt, offering_id, notes, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan_id,
                    revision,
                    row["record_id"],
                    row["course_id"],
                    row["semester"],
                    row["status"],
                    row.get("intended_category"),
                    int(row.get("attempt", 1)),
                    row.get("offering_id"),
                    str(row.get("notes", "")),
                    str(row.get("source", "manual")),
                ),
            )

    @staticmethod
    def _normalize_plan_document(
        connection: Any, curriculum_id: str, document: dict[str, Any]
    ) -> dict[str, Any]:
        def resolve(identity: str) -> str:
            stored = connection.execute(
                "SELECT catalogue_course_id FROM catalogue_courses "
                "WHERE curriculum_id = ? AND "
                "(catalogue_course_id = ? OR canonical_identity = ?)",
                (curriculum_id, identity, identity),
            ).fetchone()
            if stored is None:
                raise DegreeRepositoryError(
                    f"Degree plan references unknown curriculum course {identity}"
                )
            return str(stored["catalogue_course_id"])

        settings = dict(document.get("settings", {}))
        if "prerequisite_waivers" in settings:
            settings["prerequisite_waivers"] = [
                resolve(str(identity)) for identity in settings["prerequisite_waivers"]
            ]
        normalized = {
            **document,
            "settings": settings,
            "records": [dict(row) for row in document.get("records", [])],
        }
        for row in normalized["records"]:
            row["course_id"] = resolve(str(row.get("course_id", "")))
        return normalized


def _course_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["unresolved"] = json.loads(result.pop("unresolved_json"))
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _optional_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _now() -> str:
    return datetime.now(UTC).isoformat()
