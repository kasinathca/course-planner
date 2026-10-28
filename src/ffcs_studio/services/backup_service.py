"""Checksummed local SQLite backup and controlled restore workflow."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from ffcs_studio.persistence.database import Database, DatabaseError
from ffcs_studio.version import __version__


class BackupError(DatabaseError):
    code = "backup_error"


@dataclass(frozen=True, slots=True)
class BackupRecord:
    backup_id: str
    path: Path
    metadata: dict[str, Any]


class BackupService:
    def __init__(self, database: Database, *, retain: int = 10) -> None:
        self.database = database
        self.retain = retain
        self._lock = Lock()

    def create(self, label: str = "manual") -> dict[str, Any]:
        with self._lock, self.database.maintenance():
            path = self.database.create_backup(label, retain=self.retain)
            if path is None:
                raise BackupError("The active database does not exist")
            metadata = self._write_metadata(path, reason=label)
            return metadata

    def list(self) -> list[dict[str, Any]]:
        if not self.database.backup_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.database.backup_dir.glob("*.sqlite3"), reverse=True):
            try:
                record = self._record(path.name)
                records.append(record.metadata)
            except BackupError as exc:
                records.append(
                    {
                        "backup_id": path.name,
                        "valid": False,
                        "error": str(exc),
                        "size_bytes": path.stat().st_size,
                    }
                )
        return records

    def file(self, backup_id: str) -> Path:
        return self._record(backup_id).path

    def restore(
        self,
        backup_id: str,
        *,
        expected_sha256: str,
        confirmation: str,
        quiesce: Callable[[], None],
        reinitialize: Callable[[], None],
    ) -> dict[str, Any]:
        if confirmation != "RESTORE":
            raise BackupError("Restore confirmation must be exactly RESTORE")
        with self._lock, self.database.maintenance():
            record = self._record(backup_id)
            metadata = record.metadata
            if metadata["sha256"] != expected_sha256:
                raise BackupError("Backup checksum confirmation does not match")
            current_schema = self.database.schema_version()
            backup_schema = int(metadata["schema_version"])
            if backup_schema > current_schema:
                raise BackupError("Backup uses a newer unsupported database schema")
            quiesce()
            try:
                # Do not let retention remove the reviewed source before it is restored.
                safety_path = self.database.create_backup("pre-restore", retain=self.retain + 1000)
                if safety_path is None:
                    raise BackupError("Could not create the required pre-restore backup")
                safety_metadata = self._write_metadata(safety_path, reason="pre-restore")
                try:
                    self.database.restore_backup(record.path)
                    restored_schema = self.database.initialize()
                    critical_counts = self._critical_counts()
                except BaseException:
                    self.database.restore_backup(safety_path)
                    self.database.initialize()
                    raise
            finally:
                reinitialize()
            return {
                "status": "restored",
                "backup_id": backup_id,
                "schema_version": restored_schema,
                "critical_record_counts": critical_counts,
                "safety_backup_id": safety_metadata["backup_id"],
                "restored_at": datetime.now(UTC).isoformat(),
            }

    def _critical_counts(self) -> dict[str, int]:
        tables = (
            "import_snapshots",
            "calendar_versions",
            "saved_scenarios",
            "saved_timetable_results",
            "degree_plans",
        )
        with self.database.connection() as connection:
            self.database.verify_integrity(connection)
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }

    def _record(self, backup_id: str) -> BackupRecord:
        if not backup_id or Path(backup_id).name != backup_id or not backup_id.endswith(".sqlite3"):
            raise BackupError("Invalid backup identifier")
        path = (self.database.backup_dir / backup_id).resolve()
        root = self.database.backup_dir.resolve()
        if root not in path.parents or not path.is_file():
            raise BackupError("Backup was not found")
        metadata_path = path.with_suffix(".metadata.json")
        if not metadata_path.is_file():
            raise BackupError("Backup metadata is missing")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError("Backup metadata is invalid") from exc
        if (
            metadata.get("format") != "ffcs-studio-sqlite-backup-v1"
            or metadata.get("backup_id") != backup_id
        ):
            raise BackupError("Backup metadata format is unsupported")
        digest = _sha256(path)
        if metadata.get("sha256") != digest or metadata.get("size_bytes") != path.stat().st_size:
            raise BackupError("Backup checksum or size verification failed")
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()
                schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise BackupError("Backup is not a readable SQLite database") from exc
        if result is None or result[0] != "ok" or schema != int(metadata.get("schema_version", -1)):
            raise BackupError("Backup integrity or schema metadata verification failed")
        metadata = {**metadata, "valid": True, "integrity": "ok"}
        return BackupRecord(backup_id, path, metadata)

    def _write_metadata(self, path: Path, *, reason: str) -> dict[str, Any]:
        connection = sqlite3.connect(path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
        if integrity is None or integrity[0] != "ok":
            raise BackupError("New backup failed SQLite integrity verification")
        metadata = {
            "format": "ffcs-studio-sqlite-backup-v1",
            "backup_id": path.name,
            "created_at": datetime.now(UTC).isoformat(),
            "application_version": __version__,
            "schema_version": schema_version,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
            "integrity": "ok",
            "reason": reason,
            "retention_limit": self.retain,
            "valid": True,
        }
        path.with_suffix(".metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
