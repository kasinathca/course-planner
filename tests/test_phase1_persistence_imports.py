from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from ffcs_studio.importers.vtop_csv import (
    CsvMetadata,
    csv_metadata_from_bytes,
    prepare_csv_bytes,
)
from ffcs_studio.importers.vtop_json import prepare_json_bytes
from ffcs_studio.persistence.database import Database, MigrationError
from ffcs_studio.persistence.migrations import Migration
from ffcs_studio.persistence.repositories import Repository
from ffcs_studio.services.import_service import ImportService, StalePreview

ROOT = Path(__file__).resolve().parents[1]
THEORY = ROOT / "examples" / "vtop_selected_theory_only.json"
ETH_ELA = ROOT / "examples" / "vtop_selected_eth_ela.json"


def load_fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def encoded(value: dict[str, object], *, pretty: bool = False) -> bytes:
    indent = 2 if pretty else None
    return json.dumps(value, ensure_ascii=False, indent=indent).encode()


@pytest.fixture
def stack(tmp_path: Path) -> tuple[Database, Repository, ImportService]:
    database = Database(tmp_path / "data with spaces" / "ffcs.sqlite3")
    assert database.initialize() == 4
    repository = Repository(database)
    return database, repository, ImportService(database, repository)


def prepare(value: dict[str, object], filename: str = "capture.json"):
    result = prepare_json_bytes(encoded(value), filename=filename)
    assert result.valid
    assert result.prepared is not None
    return result.prepared


def commit_json(service: ImportService, value: dict[str, object], filename: str = "capture.json"):
    validation = service.validate_upload(
        encoded(value), filename=filename, content_type="application/json"
    )
    assert validation.validation_id
    preview = service.preview(validation.validation_id)
    return preview, service.commit(preview.preview_id)


def test_database_initializes_repeats_and_persists_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "custom Windows path" / "ffcs.sqlite3"
    database = Database(path)
    assert database.initialize() == 4
    assert database.initialize() == 4
    with database.connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    restarted = Database(path)
    assert restarted.initialize() == 4
    assert Repository(restarted).data_revision() == 0


def test_database_transaction_rolls_back_and_enforces_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    database.initialize()
    with pytest.raises(RuntimeError, match="interrupt"), database.transaction() as connection:
        connection.execute("UPDATE app_state SET data_revision = 9 WHERE singleton_id = 1")
        raise RuntimeError("interrupt")
    assert Repository(database).data_revision() == 0
    with pytest.raises(sqlite3.IntegrityError), database.transaction() as connection:
        connection.execute(
            "INSERT INTO offering_revisions("
            "offering_id, import_id, course_id, course_ordinal, raw_category, "
            "raw_course_code, raw_course_title, revision_sha256, created_at) "
            "VALUES (999, 'missing', 999, 1, 'PC', 'X', 'X', 'x', 'now')"
        )


def test_failed_migration_is_recoverable(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    with pytest.raises(MigrationError):
        database.initialize((Migration(1, "broken", "CREATE TABLE broken(;"),))
    assert database.schema_version() == 0
    assert database.initialize() == 4
    database.verify_integrity()


def test_backup_can_restore_verified_state(tmp_path: Path) -> None:
    database = Database(tmp_path / "ffcs.sqlite3")
    database.initialize()
    backup = database.create_backup("known-good")
    assert backup is not None
    with database.transaction() as connection:
        connection.execute("UPDATE app_state SET data_revision = 7 WHERE singleton_id = 1")
    assert Repository(database).data_revision() == 7
    database.restore_backup(backup)
    assert Repository(database).data_revision() == 0


@pytest.mark.parametrize(
    ("fixture", "course_count", "row_count"),
    [(THEORY, 1, 5), (ETH_ELA, 1, 12)],
)
def test_json_fixtures_prepare_without_row_loss(
    fixture: Path, course_count: int, row_count: int
) -> None:
    result = prepare_json_bytes(fixture.read_bytes(), filename=fixture.name)
    assert result.valid
    assert result.prepared is not None
    assert result.prepared.course_count == course_count
    assert result.prepared.allocation_count == row_count


def test_json_preserves_unknown_duplicate_and_zero_allocation_evidence() -> None:
    value = load_fixture(THEORY)
    course = value["courses"][0]  # type: ignore[index]
    rows = course["allocations"]  # type: ignore[index]
    rows[0]["course_type"] = "NEW-INSTITUTIONAL-TYPE"
    rows.append(copy.deepcopy(rows[0]))
    value["courses"].append(  # type: ignore[union-attr]
        {
            "category": "PE",
            "course_code": "ZERO1001",
            "course_title": "No Allocations Captured",
            "allocations": [],
        }
    )
    prepared = prepare(value)
    assert prepared.allocation_count == 6
    assert len(prepared.snapshot.courses[1].allocations) == 0
    codes = {issue.code for issue in prepared.issues}
    assert {
        "unknown_component_type",
        "duplicate_source_row",
        "duplicate_looking_allocation",
    } <= codes


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version="9.9.9"),
        lambda value: value.pop("campus"),
    ],
)
def test_json_schema_failures_are_rejected(mutation) -> None:
    value = load_fixture(THEORY)
    mutation(value)
    result = prepare_json_bytes(encoded(value), filename="invalid.json")
    assert not result.valid
    assert result.prepared is None
    assert any(issue.level == "error" for issue in result.issues)


def test_invalid_json_is_rejected() -> None:
    result = prepare_json_bytes(b"{ definitely not json", filename="invalid.json")
    assert not result.valid
    assert result.issues[0].path == "/"


def test_csv_bom_quoted_commas_combined_slots_and_repeated_rows_are_preserved() -> None:
    csv_data = (
        "\ufeffsemester_label,category,course_code,course_title,source_row,slot,venue,faculty,course_type\r\n"
        'Winter 2026,PC,CSI3002,"Applied, Cryptography",1,L27+L28,PRP352,"DOE, JANE",ELA\r\n'
        'Winter 2026,PC,CSI3002,"Applied, Cryptography",1,F1,PRP219,"DOE, JANE",ETH\r\n'
        "\r\n"
    ).encode()
    metadata = CsvMetadata("Vellore", "Winter 2026", "2026-10-28T09:00:00+05:30")
    result = prepare_csv_bytes(csv_data, filename="quoted.csv", metadata=metadata)
    assert result.valid
    assert result.prepared is not None
    rows = result.prepared.snapshot.courses[0].allocations
    assert [row.slot for row in rows] == ["L27+L28", "F1"]
    assert rows[0].faculty == "DOE, JANE"
    assert rows[0].venue == "PRP352"
    assert any(issue.code == "duplicate_source_row" for issue in result.issues)


def test_csv_sidecar_and_zero_allocation_course() -> None:
    metadata, issues = csv_metadata_from_bytes(
        json.dumps(
            {
                "campus": "Chennai",
                "semester_label": "Fall 2026",
                "captured_at": "2026-10-28T09:00:00Z",
                "zero_allocation_courses": [
                    {"category": "PE", "course_code": "ZERO1", "course_title": "Empty"}
                ],
            }
        ).encode()
    )
    assert not issues and metadata is not None
    csv_data = (
        b"semester_label,category,course_code,course_title,source_row,slot,venue,"
        b"faculty,course_type\n"
    )
    result = prepare_csv_bytes(csv_data, filename="empty.csv", metadata=metadata)
    assert result.valid
    assert result.prepared is not None
    assert result.prepared.course_count == 1
    assert result.prepared.allocation_count == 0
    assert result.prepared.metadata_origin == "sidecar"


@pytest.mark.parametrize(
    ("content", "metadata", "code"),
    [
        (
            b"wrong,headers\n1,2\n",
            CsvMetadata("V", "W", "2026-01-01T00:00:00Z"),
            "invalid_csv_headers",
        ),
        (
            b"semester_label,category,course_code,course_title,source_row,slot,venue,faculty,course_type\nW,PC,X,Title,zero,A1,R,F,TH\n",
            CsvMetadata("V", "W", "2026-01-01T00:00:00Z"),
            "invalid_csv_row",
        ),
        (
            b"semester_label,category,course_code,course_title,source_row,slot,venue,faculty,course_type\n",
            None,
            "missing_csv_metadata",
        ),
    ],
)
def test_csv_rejects_invalid_contracts(content: bytes, metadata, code: str) -> None:
    result = prepare_csv_bytes(content, filename="bad.csv", metadata=metadata)
    assert not result.valid
    assert code in {issue.code for issue in result.issues}


def test_initial_partial_and_duplicate_import_semantics(stack) -> None:
    _database, repository, service = stack
    theory = load_fixture(THEORY)
    crypto = load_fixture(ETH_ELA)
    _, first = commit_json(service, theory, "theory.json")
    _, second = commit_json(service, crypto, "crypto.json")
    assert first.status == second.status == "committed"
    listing = repository.list_offerings(
        campus="Vellore",
        semester_label="Winter Semester 2026-27",
        search=None,
        category=None,
        component=None,
        page=1,
        page_size=25,
    )
    assert listing["total"] == 2
    assert sum(item["allocation_count"] for item in listing["items"]) == 17

    validation = service.validate_upload(
        json.dumps(crypto, indent=4).encode(),
        filename="formatted-differently.json",
        content_type="application/json",
    )
    preview = service.preview(validation.validation_id or "")
    duplicate = service.commit(preview.preview_id)
    assert duplicate.status == "already_imported"
    assert repository.list_imports(page=1, page_size=25)["total"] == 2
    assert repository.data_revision() == 2


def test_reconciliation_reports_modified_removed_and_reordered_rows(stack) -> None:
    _database, _repository, service = stack
    original = load_fixture(THEORY)
    commit_json(service, original)

    changed = copy.deepcopy(original)
    rows = changed["courses"][0]["allocations"]  # type: ignore[index]
    rows[0]["venue"] = "CHANGED-ROOM"
    rows.pop()
    validation = service.validate_upload(
        encoded(changed), filename="changed.json", content_type="application/json"
    )
    report = service.preview(validation.validation_id or "").report
    assert report.updated_courses == 1
    assert report.modified_rows == 1
    assert report.removed_rows == 1
    assert report.added_rows == 0

    reordered = copy.deepcopy(original)
    reordered["courses"][0]["allocations"].reverse()  # type: ignore[index]
    validation = service.validate_upload(
        encoded(reordered), filename="reordered.json", content_type="application/json"
    )
    change = service.preview(validation.validation_id or "").report.changes[0]
    assert change.order_changed
    assert not change.added_rows and not change.removed_rows and not change.modified_rows


def test_same_course_is_scoped_by_semester_and_campus(stack) -> None:
    _database, repository, service = stack
    base = load_fixture(THEORY)
    fall = copy.deepcopy(base)
    fall["semester_label"] = "Fall Semester 2026-27"
    chennai = copy.deepcopy(base)
    chennai["campus"] = "Chennai"
    commit_json(service, base, "base.json")
    commit_json(service, fall, "fall.json")
    commit_json(service, chennai, "chennai.json")
    assert len(repository.semesters()) == 3


def test_stale_and_conflicting_previews_are_rejected(stack) -> None:
    _database, repository, service = stack
    first_value = load_fixture(THEORY)
    second_value = load_fixture(ETH_ELA)
    first_validation = service.validate_upload(
        encoded(first_value), filename="first.json", content_type="application/json"
    )
    second_validation = service.validate_upload(
        encoded(second_value), filename="second.json", content_type="application/json"
    )
    first_preview = service.preview(first_validation.validation_id or "")
    second_preview = service.preview(second_validation.validation_id or "")
    service.commit(first_preview.preview_id)
    with pytest.raises(StalePreview):
        service.commit(second_preview.preview_id)
    assert repository.data_revision() == 1


def test_failed_commit_rolls_back_all_active_data(stack, monkeypatch) -> None:
    _database, repository, service = stack
    value = load_fixture(THEORY)
    value["courses"].append(copy.deepcopy(load_fixture(ETH_ELA)["courses"][0]))  # type: ignore[union-attr,index]
    validation = service.validate_upload(
        encoded(value), filename="two.json", content_type="application/json"
    )
    preview = service.preview(validation.validation_id or "")
    original_apply = repository.apply_offering_revision
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("simulated write failure")
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(repository, "apply_offering_revision", fail_second)
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        service.commit(preview.preview_id)
    assert repository.data_revision() == 0
    assert repository.list_imports(page=1, page_size=25)["total"] == 0
    assert (
        repository.list_offerings(
            campus=None,
            semester_label=None,
            search=None,
            category=None,
            component=None,
            page=1,
            page_size=25,
        )["total"]
        == 0
    )


def test_restart_recovers_committed_records(stack) -> None:
    database, _repository, service = stack
    _, outcome = commit_json(service, load_fixture(ETH_ELA))
    restarted_database = Database(database.path)
    assert restarted_database.initialize() == 4
    restarted = Repository(restarted_database)
    detail = restarted.import_detail(outcome.import_id)
    assert detail is not None
    assert detail["allocation_count"] == 12
    offerings = restarted.list_offerings(
        campus="Vellore",
        semester_label="Winter Semester 2026-27",
        search="cryptography",
        category="PC",
        component="ELA",
        page=1,
        page_size=10,
    )
    assert offerings["total"] == 1
    offering_id = offerings["items"][0]["offering_id"]
    assert len(restarted.offering_allocations(int(offering_id)) or []) == 12
