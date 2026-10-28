from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from ffcs_studio.config import Settings
from ffcs_studio.importers.vtop_csv import csv_metadata_from_bytes, prepare_csv_bytes
from ffcs_studio.persistence.database import Database
from ffcs_studio.persistence.repositories import Repository
from ffcs_studio.services.backup_service import BackupError, BackupService
from ffcs_studio.services.import_service import ImportService
from ffcs_studio.services.interoperability import (
    InterchangeError,
    SemesterExportService,
    inspect_xlsx_rows,
    parse_ffcsinator_typescript,
)
from ffcs_studio.validation import validate_json_bytes
from ffcs_studio.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8765"


def _seed(database: Database, fixture: str = "vtop_selected_eth_ela.json") -> None:
    repository = Repository(database)
    service = ImportService(database, repository)
    content = (ROOT / "examples" / fixture).read_bytes()
    validated = service.validate_upload(
        content,
        filename=fixture,
        content_type="application/json",
    )
    assert validated.validation_id
    preview = service.preview(validated.validation_id)
    assert service.commit(preview.preview_id).status == "committed"


def test_cross_format_exports_preserve_rows_and_formula_safety(tmp_path: Path) -> None:
    database = Database(tmp_path / "source.sqlite3")
    assert database.initialize() == 4
    _seed(database)
    exports = SemesterExportService(database)
    snapshot = exports.snapshot(campus="Vellore", semester_label="Winter Semester 2026-27")
    assert snapshot.allocation_count == 12

    canonical = exports.canonical_json(snapshot)
    report = validate_json_bytes(canonical, source_name="export.json")
    assert report.valid
    payload = json.loads(canonical)
    expected = [
        (row["source_row"], row["slot"], row["venue"], row["faculty"], row["course_type"])
        for row in payload["courses"][0]["allocations"]
    ]

    csv_content, sidecar_content = exports.csv_and_sidecar(snapshot)
    metadata, issues = csv_metadata_from_bytes(sidecar_content)
    assert not issues and metadata
    csv_import = prepare_csv_bytes(csv_content, filename="roundtrip.csv", metadata=metadata)
    assert csv_import.valid and csv_import.prepared
    actual = [
        (row.source_row, row.slot, row.venue, row.faculty, row.course_type)
        for row in csv_import.prepared.snapshot.courses[0].allocations
    ]
    assert actual == expected

    xlsx_rows = inspect_xlsx_rows(exports.xlsx(snapshot))
    assert len(xlsx_rows) == 13
    assert [(row[4], row[5], row[7], row[6], row[8]) for row in xlsx_rows[1:]] == expected

    with database.transaction() as connection:
        connection.execute(
            "UPDATE allocation_rows SET raw_faculty = '=HYPERLINK(\"https://bad.invalid\")' "
            "WHERE allocation_id = (SELECT MIN(allocation_id) FROM allocation_rows)"
        )
    guarded = exports.snapshot(campus="Vellore", semester_label="Winter Semester 2026-27")
    guarded_csv, _ = exports.csv_and_sidecar(guarded)
    assert b"'=HYPERLINK" in guarded_csv
    assert inspect_xlsx_rows(exports.xlsx(guarded))[1][6].startswith("'=HYPERLINK")
    assert "'=HYPERLINK" not in exports.canonical_json(guarded).decode("utf-8")


def test_ffcsinator_parser_is_bounded_non_executing_and_reports_loss(tmp_path: Path) -> None:
    text = """export default {
      'CSI3001L - Cloud Computing': [
        {slot: 'A1+TA1', venue: 'SJT-101', faculty: 'FACULTY A'},
        {slot: 'A1+TA1', venue: 'SJT-101', faculty: 'FACULTY A'},
      ],
      'CSI3001P - Cloud Computing': [
        {slot: 'L1+L2+L15+L16', venue: 'LAB-1', faculty: 'FACULTY A'},
      ],
    };"""
    canonical, diagnostics = parse_ffcsinator_typescript(
        text,
        filename="ProgrammeCore.ts",
        campus="Vellore",
        semester_label="Synthetic Semester",
    )
    assert canonical["source"] == "legacy-ffcsinator"
    assert len(canonical["courses"]) == 1
    rows = canonical["courses"][0]["allocations"]
    assert [row["source_row"] for row in rows] == [1, 2, 3]
    assert rows[0] == {**rows[1], "source_row": 1}
    assert rows[2]["slot"] == "L1+L2+L15+L16"
    assert {row["course_type"] for row in rows} == {
        "UNKNOWN_LEGACY_THEORY_SIDE",
        "UNKNOWN_LEGACY_PRACTICAL_SIDE",
    }
    assert len(diagnostics) == 3

    for malicious in (
        "fetch('https://bad.invalid'); export default {};",
        "export default (() => ({}))();",
        "export default {x: [`template`]};",
        "export default {x: [{slot:'A',venue:'V',faculty:process.env.SECRET}]};",
    ):
        with pytest.raises(InterchangeError):
            parse_ffcsinator_typescript(
                malicious,
                filename="ProgrammeCore.ts",
                campus="Vellore",
                semester_label="Synthetic Semester",
            )

    database = Database(tmp_path / "source.sqlite3")
    database.initialize()
    _seed(database)
    archive = SemesterExportService(database).ffcsinator_zip(
        SemesterExportService(database).snapshot(
            campus="Vellore", semester_label="Winter Semester 2026-27"
        )
    )
    assert b"ffcs-studio-sidecar.json" in archive


def test_ffcsinator_adapter_uses_reviewed_import_pipeline(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            converted = await client.post(
                "/api/v1/data/ffcsinator/convert",
                headers=headers,
                json={
                    "filename": "ProgrammeCore.ts",
                    "campus": "Vellore",
                    "semester_label": "Synthetic Semester",
                    "content": (ROOT / "examples" / "ProgrammeCore.ts").read_text(encoding="utf-8"),
                },
            )
            assert converted.status_code == 200, converted.text
            payload = converted.json()
            assert payload["source"] == "legacy-ffcsinator"
            assert payload["canonical"]["source"] == "legacy-ffcsinator"
            preview = await client.post(
                "/api/v1/imports/preview",
                headers=headers,
                json={"validation_id": payload["validation_id"]},
            )
            assert preview.status_code == 200, preview.text
            committed = await client.post(
                "/api/v1/imports/commit",
                headers=headers,
                json={"preview_id": preview.json()["preview_id"]},
            )
            assert committed.status_code == 200, committed.text
            detail = await client.get(f"/api/v1/imports/{committed.json()['import_id']}")
            assert detail.json()["source_kind"] == "legacy-ffcsinator"
        await app.router.shutdown()

    asyncio.run(run())


def test_backup_metadata_integrity_restore_and_failure_preserves_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "active.sqlite3")
    database.initialize()
    _seed(database, "vtop_selected_theory_only.json")
    service = BackupService(database)
    backup = service.create("test")
    assert backup["valid"] and backup["schema_version"] == 4
    assert service.list()[0]["integrity"] == "ok"

    with database.transaction() as connection:
        connection.execute("UPDATE app_state SET data_revision = 99")
    events: list[str] = []
    restored = service.restore(
        backup["backup_id"],
        expected_sha256=backup["sha256"],
        confirmation="RESTORE",
        quiesce=lambda: events.append("stopped"),
        reinitialize=lambda: events.append("started"),
    )
    assert restored["status"] == "restored"
    assert restored["critical_record_counts"]["import_snapshots"] == 1
    assert Repository(database).data_revision() == 1
    assert events == ["stopped", "started"]

    with pytest.raises(BackupError):
        service.restore(
            backup["backup_id"],
            expected_sha256="0" * 64,
            confirmation="RESTORE",
            quiesce=lambda: None,
            reinitialize=lambda: None,
        )
    assert Repository(database).data_revision() == 1

    with database.transaction() as connection:
        connection.execute("UPDATE app_state SET data_revision = 77")
    original_restore = Database.restore_backup
    restore_calls = 0

    def interrupted_restore(target: Database, path: Path) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            raise OSError("simulated interrupted restore")
        original_restore(target, path)

    interrupted_events: list[str] = []
    with monkeypatch.context() as patcher:
        patcher.setattr(Database, "restore_backup", interrupted_restore)
        with pytest.raises(OSError, match="simulated interrupted restore"):
            service.restore(
                backup["backup_id"],
                expected_sha256=backup["sha256"],
                confirmation="RESTORE",
                quiesce=lambda: interrupted_events.append("stopped"),
                reinitialize=lambda: interrupted_events.append("started"),
            )
    assert Repository(database).data_revision() == 77
    assert interrupted_events == ["stopped", "started"]

    future = service.create("future-schema")
    future_path = service.file(future["backup_id"])
    connection = sqlite3.connect(future_path)
    try:
        connection.execute("PRAGMA user_version = 999")
        connection.commit()
    finally:
        connection.close()
    metadata_path = future_path.with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = 999
    metadata["sha256"] = hashlib.sha256(future_path.read_bytes()).hexdigest()
    metadata["size_bytes"] = future_path.stat().st_size
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(BackupError, match="newer unsupported"):
        service.restore(
            future["backup_id"],
            expected_sha256=metadata["sha256"],
            confirmation="RESTORE",
            quiesce=lambda: None,
            reinitialize=lambda: None,
        )
    assert Repository(database).data_revision() == 77

    with database.transaction() as connection:
        connection.execute("UPDATE app_state SET data_revision = 1")

    path = service.file(backup["backup_id"])
    path.write_bytes(b"corrupt")
    corrupted = next(item for item in service.list() if item["backup_id"] == backup["backup_id"])
    assert corrupted["valid"] is False
    assert Repository(database).data_revision() == 1


def test_scenario_import_validate_preview_commit_never_overwrites(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            document = {
                "schema_version": "1.0",
                "campus": "",
                "semester_label": "",
                "calendar_id": None,
                "mode": "exploratory",
                "courses": [],
                "occupied_intervals": [],
                "credit_constraints": {
                    "minimum": None,
                    "target": None,
                    "maximum": None,
                    "category_minimums": {},
                    "category_maximums": {},
                },
                "ranking": {
                    "preferred_faculties": [],
                    "prefer_morning_theory": False,
                    "prefer_evening_theory": False,
                    "avoid_late_after_minute": None,
                    "minimize_labs": True,
                    "minimize_campus_days": True,
                },
                "provisional_policy": {
                    "allow_unverified_calendar": False,
                    "allow_user_supplied_metadata": False,
                    "allow_provisional_pairing": False,
                    "allow_unknown_pairing": False,
                    "allow_same_faculty_pairing": False,
                },
                "top_k": 20,
                "max_search_nodes": 2000000,
            }
            source = await client.post(
                "/api/v1/scenarios",
                headers=headers,
                json={"name": "Source", "description": "safe", "document": document},
            )
            assert source.status_code == 201, source.text
            source_id = source.json()["scenario_id"]
            exported = (await client.get(f"/api/v1/scenarios/{source_id}/export")).json()
            validated = await client.post(
                "/api/v1/scenarios/import/validate",
                headers=headers,
                json={"document": exported},
            )
            assert validated.status_code == 200, validated.text
            preview = await client.post(
                "/api/v1/scenarios/import/preview",
                headers=headers,
                json={"validation_id": validated.json()["validation_id"]},
            )
            assert preview.json()["identity_conflict"] is True
            committed = await client.post(
                "/api/v1/scenarios/import/commit",
                headers=headers,
                json={
                    "preview_id": preview.json()["preview_id"],
                    "choice": "create_new",
                    "name": "Imported copy",
                },
            )
            assert committed.status_code == 201, committed.text
            assert committed.json()["scenario_id"] != source_id
            assert (await client.get("/api/v1/scenarios")).json()["total"] == 2

            malformed = await client.post(
                "/api/v1/scenarios/import/validate",
                headers=headers,
                json={"document": {**exported, "trusted_verified": True}},
            )
            assert malformed.status_code == 422
        await app.router.shutdown()

    asyncio.run(run())


def test_userscript_is_narrow_manual_and_has_async_fixture_harness() -> None:
    script = (ROOT / "integrations/vtop/ffcs-studio-vtop-collector.user.js").read_text(
        encoding="utf-8"
    )
    assert "@match        https://vtop.vit.ac.in/vtop/*" in script
    assert "@connect      none" in script
    assert "MutationObserver" in script
    assert "document.body" not in script
    assert "setInterval" not in script
    assert "window.fetch" not in script
    assert "XMLHttpRequest" not in script
    assert "courseDetailFragement" in script
    assert "PRIVATE" not in script
    harness = (ROOT / "integrations/vtop/tests/collector-harness.html").read_text(encoding="utf-8")
    for case in (
        "duplicateRowsPreserved",
        "fourPeriodLabPreserved",
        "noStaleRow",
        "noPiiLeak",
    ):
        assert case in harness


def test_windows_launcher_anchors_to_its_own_directory() -> None:
    launcher = (ROOT / "Start FFCS Studio.cmd").read_text(encoding="utf-8")
    assert "%~dp0" in launcher
    assert "%FFCS_ROOT%scripts\\start.ps1" in launcher
    assert "ExecutionPolicy Bypass" in launcher
    assert "setx" not in launcher.casefold()
