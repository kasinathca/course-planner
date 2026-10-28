from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ffcs_studio.degree.importers import parse_curriculum, parse_legacy_v6
from ffcs_studio.persistence.database import Database
from ffcs_studio.persistence.degree_repository import DegreeRepository, DegreeRevisionConflict
from ffcs_studio.persistence.migrations import packaged_migrations


def synthetic_curriculum() -> dict[str, object]:
    categories = [
        {
            "code": "PC",
            "name": "Programme Core",
            "recorded_target_milli": 81000,
            "confirmed_credit_target_milli": 81000,
        },
        {
            "code": "PE",
            "name": "Programme Elective",
            "recorded_target_milli": 48000,
            "confirmed_credit_target_milli": 48000,
        },
        {
            "code": "UC",
            "name": "University Core",
            "recorded_target_milli": 61000,
            "confirmed_credit_target_milli": 61000,
        },
        {
            "code": "UE",
            "name": "University Elective",
            "recorded_target_milli": 12000,
            "confirmed_credit_target_milli": 12000,
        },
        {
            "code": "SPE",
            "name": "Specialization Elective",
            "recorded_target_milli": 18000,
            "confirmed_credit_target_milli": 18000,
        },
        {
            "code": "BC",
            "name": "Bridge Course",
            "recorded_target_milli": 0,
            "confirmed_credit_target_milli": 0,
        },
        {
            "code": "NC",
            "name": "Non-Credit Course",
            "recorded_target_milli": 5000,
            "confirmed_credit_target_milli": None,
            "non_credit_target_units": 5,
            "counted_in_graduation": None,
        },
    ]
    return {
        "schema_version": "1.0",
        "programme": {
            "programme_code": "SYNTHETIC-IMTECH",
            "name": "Synthetic Integrated Programme",
            "admission_batch": "TEST-ONLY",
            "revision_code": "synthetic-v1",
            "displayed_total_milli": 225000,
            "categories": categories,
        },
        "courses": [
            {
                "canonical_id": "syn-pc",
                "source_id": "legacy-pc",
                "code": "SYN1001",
                "title": "Synthetic Core",
                "category": "PC",
                "curriculum_type": "TH",
                "credits": "4",
                "provenance": "user_supplied",
            },
            {
                "canonical_id": "syn-pe",
                "source_id": "legacy-pe",
                "code": "SYN2001",
                "title": "Synthetic Elective",
                "category": "PE",
                "curriculum_type": "ETL",
                "credits": "3.5",
                "provenance": "user_supplied",
            },
            {
                "canonical_id": "sts-a",
                "source_id": "sts-source-a",
                "code": "STS3022",
                "title": "Synthetic STS Option A",
                "category": "UC",
                "curriculum_type": "LO",
                "credits": "1",
                "provenance": "legacy",
            },
            {
                "canonical_id": "sts-b",
                "source_id": "sts-source-b",
                "code": "STS3022",
                "title": "Synthetic STS Option B",
                "category": "UC",
                "curriculum_type": "LO",
                "credits": "1",
                "provenance": "legacy",
            },
            {
                "canonical_id": "syn-unknown",
                "source_id": "unknown",
                "code": "SYN9999",
                "title": "Synthetic Unknown Credit",
                "category": "UE",
                "curriculum_type": "UNKNOWN",
                "credits": None,
                "provenance": "user_supplied",
                "unresolved": ["credits"],
            },
        ],
        "relationships": [
            {
                "relationship_id": "sts-basket",
                "relationship_type": "basket",
                "course_ids": ["sts-a", "sts-b"],
                "requirement_key": "sts-requirement",
                "verified": True,
                "provenance": "legacy",
                "notes": "Synthetic test relationship",
            }
        ],
        "prerequisites": [
            {
                "rule_id": "syn-pe-prerequisite",
                "course_id": "syn-pe",
                "all_of": ["syn-pc"],
                "any_of": [],
                "minimum_semester": 5,
                "verified": True,
                "provenance": "user_supplied",
            }
        ],
    }


def plan_document() -> dict[str, object]:
    return {
        "programme_code": "SYNTHETIC-IMTECH",
        "curriculum_revision": "synthetic-v1",
        "records": [
            {
                "record_id": "r-pc",
                "course_id": "syn-pc",
                "semester": 5,
                "status": "completed",
                "intended_category": "PC",
                "attempt": 1,
                "notes": "",
                "source": "manual",
                "offering_id": None,
            },
            {
                "record_id": "r-pe",
                "course_id": "syn-pe",
                "semester": 6,
                "status": "planned",
                "intended_category": "PE",
                "attempt": 1,
                "notes": "",
                "source": "manual",
                "offering_id": None,
            },
        ],
        "settings": {},
        "semester_labels": {},
    }


def test_migration_0004_preserves_phase4_records_and_creates_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    assert database.initialize(packaged_migrations()[:3]) == 3
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO saved_scenarios("
            "scenario_id, name, description, campus, semester_label, calendar_id, "
            "document_schema_version, current_revision, status, created_at, updated_at"
            ") VALUES ("
            "'phase4', 'Preserved', '', 'Vellore', '', NULL, '1.0', "
            "1, 'draft', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO scenario_revisions("
            "scenario_id, revision, document_json, source_references_json, status, "
            "change_summary, created_at"
            ") VALUES ('phase4', 1, '{}', '{}', 'draft', 'preserve', 'now')"
        )
    assert database.initialize() == 4
    with database.connection() as connection:
        assert (
            connection.execute(
                "SELECT name FROM saved_scenarios WHERE scenario_id = 'phase4'"
            ).fetchone()[0]
            == "Preserved"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "degree_plans",
            "catalogue_courses",
            "registration_availability_history",
            "recovery_runs",
        } <= tables
    assert list(database.backup_dir.glob("*.sqlite3"))


def test_curriculum_import_plan_revision_restart_and_optimistic_conflict(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    assert database.initialize() == 4
    repository = DegreeRepository(database)
    repository.ensure_programme()
    committed = repository.commit_curriculum(
        parse_curriculum(synthetic_curriculum()), filename="synthetic.json"
    )
    assert committed["duplicate"] is False
    import_backups = list(database.backup_dir.glob("*-pre-degree-import.sqlite3"))
    assert len(import_backups) == 1
    duplicate = repository.commit_curriculum(
        parse_curriculum(synthetic_curriculum()), filename="copy.json"
    )
    assert duplicate["duplicate"] is True
    assert list(database.backup_dir.glob("*-pre-degree-import.sqlite3")) == import_backups
    curriculum_id = str(committed["curriculum_id"])
    revised_source = deepcopy(synthetic_curriculum())
    revised_source["programme"]["revision_code"] = "synthetic-v2"  # type: ignore[index]
    revised_source["programme"]["revision_name"] = "Synthetic revision 2"  # type: ignore[index]
    revised = repository.commit_curriculum(
        parse_curriculum(revised_source), filename="synthetic-v2.json"
    )
    assert revised["duplicate"] is False
    original_pc = repository.list_catalogue(curriculum_id, query="SYN1001")["items"][0]
    revised_pc = repository.list_catalogue(str(revised["curriculum_id"]), query="SYN1001")["items"][
        0
    ]
    assert original_pc["canonical_identity"] == revised_pc["canonical_identity"] == "syn-pc"
    assert original_pc["catalogue_course_id"] != revised_pc["catalogue_course_id"]
    catalog = repository.list_catalogue(curriculum_id, query="STS3022", page_size=100)
    assert catalog["total"] == 2
    assert {item["source_identity"] for item in catalog["items"]} == {
        "sts-source-a",
        "sts-source-b",
    }

    created = repository.create_plan(
        name="Primary", curriculum_id=curriculum_id, document=plan_document()
    )
    plan_id = str(created["degree_plan_id"])
    changed = plan_document()
    changed["records"][1]["semester"] = 7  # type: ignore[index]
    updated = repository.update_plan(
        plan_id,
        expected_revision=1,
        name="Primary",
        document=changed,
        change_summary="Move PE to semester 7",
    )
    assert updated["current_revision"] == 2
    assert repository.compare_plans(plan_id, 1, 2)["changed"][0]["after"]["semester"] == 7
    with pytest.raises(DegreeRevisionConflict):
        repository.update_plan(
            plan_id, expected_revision=1, name="Stale", document=changed, change_summary="must fail"
        )
    restored = repository.restore_plan(plan_id, source_revision=1, expected_revision=2)
    assert restored["current_revision"] == 3
    assert restored["document"]["records"][1]["semester"] == 6
    copied = repository.duplicate_plan(plan_id, name="Alternative")
    assert copied["degree_plan_id"] != plan_id
    assert DegreeRepository(Database(database.path)).get_plan(plan_id)["current_revision"] == 3


def test_legacy_snapshots_are_idempotent_and_not_unioned(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    database.initialize()
    repository = DegreeRepository(database)
    payload = {
        "version": 6,
        "catalog": [{"id": "course-a", "code": "SYN", "title": "Synthetic"}],
        "completed": [],
        "plan": {"semester10": []},
        "settings": {},
        "offerings": {},
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    parsed = parse_legacy_v6(payload, source_name="snapshot.json", source_sequence=5)
    assert repository.commit_legacy(parsed)["duplicate"] is False
    assert repository.commit_legacy(parsed)["duplicate"] is True
    imports = repository.list_legacy_imports()
    assert len(imports) == 1
    assert imports[0]["source_sequence"] == 5
    assert imports[0]["preview"]["plan"] == []
