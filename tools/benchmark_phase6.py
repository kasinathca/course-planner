"""Reproducible sanitized Phase 6 interchange and backup measurements."""

from __future__ import annotations

import json
import statistics
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from ffcs_studio.config import Settings
from ffcs_studio.persistence.database import Database
from ffcs_studio.persistence.repositories import Repository
from ffcs_studio.services.backup_service import BackupService
from ffcs_studio.services.import_service import ImportService
from ffcs_studio.services.interoperability import (
    SemesterExportService,
    parse_ffcsinator_typescript,
)
from ffcs_studio.web.app import create_app


def measure(operation, repeats: int = 5):  # type: ignore[no-untyped-def]
    durations = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = operation()
        durations.append((time.perf_counter() - started) * 1000)
    return result, statistics.median(durations), max(durations)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ffcs-phase6-") as directory:
        root = Path(directory)
        database = Database(root / "benchmark.sqlite3")
        database.initialize()
        service = ImportService(database, Repository(database))
        payload = fixture()
        raw = json.dumps(payload).encode()
        validated = service.validate_upload(
            raw, filename="synthetic-181.json", content_type="application/json"
        )
        assert validated.validation_id
        preview = service.preview(validated.validation_id)
        service.commit(preview.preview_id)
        exports = SemesterExportService(database)
        snapshot = exports.snapshot(campus="Synthetic", semester_label="Synthetic 181-row term")

        tracemalloc.start()
        _, json_median, json_max = measure(lambda: exports.canonical_json(snapshot))
        workbook, xlsx_median, xlsx_max = measure(lambda: exports.xlsx(snapshot), 3)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        legacy = legacy_fixture()
        _, legacy_median, legacy_max = measure(
            lambda: parse_ffcsinator_typescript(
                legacy,
                filename="ProgrammeElective.ts",
                campus="Synthetic",
                semester_label="Synthetic term",
            )
        )
        backups = BackupService(database)
        backup, backup_median, backup_max = measure(lambda: backups.create("benchmark"), 3)
        _, restore_median, restore_max = measure(
            lambda: backups.restore(
                backup["backup_id"],
                expected_sha256=backup["sha256"],
                confirmation="RESTORE",
                quiesce=lambda: None,
                reinitialize=lambda: None,
            ),
            3,
        )
        _, startup_median, startup_max = measure(
            lambda: create_app(
                Settings(data_dir=root / "startup", database_name="startup.sqlite3")
            ),
            3,
        )
        print(
            json.dumps(
                {
                    "measured_at": datetime.now(UTC).isoformat(),
                    "courses": len(snapshot.courses),
                    "allocation_rows": snapshot.allocation_count,
                    "xlsx_bytes": len(workbook),
                    "peak_traced_bytes_json_xlsx": peak,
                    "json_export_ms": [json_median, json_max],
                    "xlsx_export_ms": [xlsx_median, xlsx_max],
                    "legacy_ts_parse_ms": [legacy_median, legacy_max],
                    "backup_ms": [backup_median, backup_max],
                    "restore_ms": [restore_median, restore_max],
                    "application_factory_ms": [startup_median, startup_max],
                },
                indent=2,
            )
        )


def fixture() -> dict[str, object]:
    courses = []
    remaining = 181
    for course_index in range(30):
        row_count = min(7, remaining)
        remaining -= row_count
        courses.append(
            {
                "category": ("PC", "PE", "UC", "UE", "SPE")[course_index % 5],
                "course_code": f"SYN{course_index:04d}",
                "course_title": f"Synthetic benchmark course {course_index}",
                "allocations": [
                    {
                        "source_row": row + 1,
                        "slot": f"A{1 + row % 2}",
                        "venue": f"ROOM-{row}",
                        "faculty": f"SYNTHETIC FACULTY {row}",
                        "course_type": "ETH" if row % 2 == 0 else "ELA",
                    }
                    for row in range(row_count)
                ],
            }
        )
    assert remaining == 0
    return {
        "schema_version": "1.0.0",
        "source": "vtop-tampermonkey",
        "campus": "Synthetic",
        "semester_label": "Synthetic 181-row term",
        "captured_at": "2026-01-01T00:00:00+00:00",
        "courses": courses,
    }


def legacy_fixture() -> str:
    entries = []
    for course_index in range(30):
        rows = ",".join(
            f"{{slot:'A{1 + row % 2}',venue:'ROOM-{row}',faculty:'FACULTY {row}'}}"
            for row in range(6)
        )
        entries.append(f"'SYN{course_index:04d}L - Synthetic {course_index}':[{rows}]")
    return "export default {" + ",".join(entries) + "};"


if __name__ == "__main__":
    main()
