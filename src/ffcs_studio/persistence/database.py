"""SQLite initialization, migrations, transactions, integrity, and backups."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from ffcs_studio.persistence.migrations import Migration, packaged_migrations


class DatabaseError(RuntimeError):
    """Base persistence failure."""


class MigrationError(DatabaseError):
    """A schema migration could not be applied atomically."""


@dataclass(slots=True)
class Database:
    path: Path
    busy_timeout_ms: int = 5_000
    _maintenance_lock: RLock = field(default_factory=RLock, init=False, repr=False)

    @property
    def backup_dir(self) -> Path:
        return self.path.parent / "backups"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def initialize(self, migrations: tuple[Migration, ...] | None = None) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        selected = migrations if migrations is not None else packaged_migrations()
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            available = {migration.version for migration in selected}
            unsupported = applied - available
            if unsupported:
                raise MigrationError(
                    f"database contains unsupported migration versions: {sorted(unsupported)}"
                )
            pending = tuple(migration for migration in selected if migration.version not in applied)
            if pending and existed:
                connection.close()
                self.create_backup("pre-migration")
                connection = self.connect()
            for migration in pending:
                script = _migration_script(migration)
                try:
                    connection.executescript(script)
                except sqlite3.Error as exc:
                    with suppress(sqlite3.Error):
                        connection.execute("ROLLBACK")
                    raise MigrationError(
                        f"migration {migration.version} ({migration.name}) failed"
                    ) from exc
            self.verify_integrity(connection)
            version_row = connection.execute("PRAGMA user_version").fetchone()
            schema_version = int(version_row[0])
            expected_version = max(available, default=0)
            if schema_version != expected_version:
                raise MigrationError(
                    f"database schema version {schema_version} does not match {expected_version}"
                )
            return schema_version
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._maintenance_lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def maintenance(self) -> Iterator[None]:
        """Block coordinated writers while a multi-step maintenance operation runs."""

        with self._maintenance_lock:
            yield

    def schema_version(self) -> int:
        with self.connection() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            return int(row[0])

    def verify_integrity(self, connection: sqlite3.Connection | None = None) -> None:
        owned = connection is None
        current = connection or self.connect()
        try:
            quick_check = current.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or quick_check[0] != "ok":
                raise DatabaseError("SQLite integrity check failed")
            if current.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise DatabaseError("SQLite foreign key integrity check failed")
        finally:
            if owned:
                current.close()

    def create_backup(self, label: str, *, retain: int = 10) -> Path | None:
        with self._maintenance_lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return None
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            safe_label = "".join(
                character for character in label if character.isalnum() or character in "-_"
            )
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            destination = self.backup_dir / f"{timestamp}-{safe_label or 'backup'}.sqlite3"
            source = self.connect()
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                target.close()
                source.close()
            backups = sorted(self.backup_dir.glob("*.sqlite3"), reverse=True)
            for expired in backups[retain:]:
                expired.unlink(missing_ok=True)
                expired.with_suffix(".metadata.json").unlink(missing_ok=True)
            return destination

    def restore_backup(self, backup: Path) -> None:
        with self._maintenance_lock:
            resolved = backup.resolve()
            backup_root = self.backup_dir.resolve()
            if backup_root not in resolved.parents or not resolved.is_file():
                raise DatabaseError("backup must be a file in the configured backup directory")
            temporary = self.path.with_suffix(".restore.tmp")
            rollback = self.path.with_suffix(".restore.rollback")
            temporary.unlink(missing_ok=True)
            rollback.unlink(missing_ok=True)
            source = sqlite3.connect(resolved)
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            candidate = Database(temporary, self.busy_timeout_ms)
            try:
                candidate.verify_integrity()
                if self.path.exists():
                    shutil.copy2(self.path, rollback)
                for suffix in ("-wal", "-shm"):
                    Path(f"{self.path}{suffix}").unlink(missing_ok=True)
                temporary.replace(self.path)
                self.verify_integrity()
            except BaseException:
                if rollback.exists():
                    rollback.replace(self.path)
                temporary.unlink(missing_ok=True)
                raise
            finally:
                rollback.unlink(missing_ok=True)


def _migration_script(migration: Migration) -> str:
    return (
        "BEGIN IMMEDIATE;\n"
        f"{migration.sql}\n"
        "INSERT INTO schema_migrations(version, name, applied_at) VALUES "
        f"({migration.version}, {_sql_quote(migration.name)}, {_sql_quote(_utc_now())});\n"
        f"PRAGMA user_version = {migration.version};\n"
        "COMMIT;"
    )


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
