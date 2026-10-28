"""Bounded validate → preview → atomic commit orchestration."""

from __future__ import annotations

import secrets
import sqlite3
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from threading import Lock, RLock

from ffcs_studio.importers import (
    CsvMetadata,
    PreparationResult,
    PreparedImport,
    prepare_csv_bytes,
    prepare_json_bytes,
)
from ffcs_studio.persistence.database import Database
from ffcs_studio.persistence.repositories import Repository, utc_now
from ffcs_studio.services.reconciliation import ReconciliationReport, reconcile
from ffcs_studio.validation import ValidationIssue


class ImportServiceError(RuntimeError):
    code = "import_error"


class UnsupportedUpload(ImportServiceError):
    code = "unsupported_media_type"


class UnsafeFilename(ImportServiceError):
    code = "unsafe_filename"


class TemporaryRecordNotFound(ImportServiceError):
    code = "temporary_record_not_found"


class StalePreview(ImportServiceError):
    code = "stale_preview"


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    prepared: PreparedImport


@dataclass(frozen=True, slots=True)
class PreviewRecord:
    prepared: PreparedImport
    report: ReconciliationReport


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    validation_id: str | None
    expires_at: str | None
    result: PreparationResult


@dataclass(frozen=True, slots=True)
class PreviewOutcome:
    preview_id: str
    expires_at: str
    prepared: PreparedImport
    report: ReconciliationReport


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    status: str
    import_id: str
    data_revision: int
    course_count: int
    allocation_count: int
    backup_created: bool


class ExpiringStore[T]:
    def __init__(self, *, max_entries: int, ttl_seconds: int) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = RLock()

    def put(self, value: T) -> tuple[str, str]:
        with self._lock:
            self._purge()
            while len(self._entries) >= self._max_entries:
                self._entries.popitem(last=False)
            token = secrets.token_urlsafe(32)
            expires_monotonic = time.monotonic() + self._ttl_seconds
            self._entries[token] = (expires_monotonic, value)
            expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
            return token, expires_at.isoformat()

    def get(self, token: str) -> T:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                raise TemporaryRecordNotFound("temporary import record was not found or expired")
            if entry[0] <= time.monotonic():
                del self._entries[token]
                raise TemporaryRecordNotFound("temporary import record was not found or expired")
            self._entries.move_to_end(token)
            return entry[1]

    def pop(self, token: str) -> None:
        with self._lock:
            self._entries.pop(token, None)

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [token for token, (deadline, _) in self._entries.items() if deadline <= now]
        for token in expired:
            del self._entries[token]


class ImportService:
    def __init__(
        self,
        database: Database,
        repository: Repository,
        *,
        max_temporary_entries: int = 20,
        preview_ttl_seconds: int = 900,
    ) -> None:
        self.database = database
        self.repository = repository
        self._validated = ExpiringStore[ValidatedUpload](
            max_entries=max_temporary_entries,
            ttl_seconds=preview_ttl_seconds,
        )
        self._previews = ExpiringStore[PreviewRecord](
            max_entries=max_temporary_entries,
            ttl_seconds=preview_ttl_seconds,
        )
        self._commit_lock = Lock()

    def validate_upload(
        self,
        content: bytes,
        *,
        filename: str,
        content_type: str,
        csv_metadata: CsvMetadata | None = None,
    ) -> ValidationOutcome:
        safe_name = _safe_filename(filename)
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type in {"application/json", "text/json"}:
            result = prepare_json_bytes(content, filename=safe_name)
        elif media_type in {"text/csv", "application/csv", "application/vnd.ms-excel"}:
            result = prepare_csv_bytes(content, filename=safe_name, metadata=csv_metadata)
        else:
            raise UnsupportedUpload(f"unsupported upload content type {media_type!r}")
        if not result.valid or result.prepared is None:
            return ValidationOutcome(None, None, result)
        validation_id, expires_at = self._validated.put(ValidatedUpload(result.prepared))
        return ValidationOutcome(validation_id, expires_at, result)

    def validate_prepared(self, prepared: PreparedImport) -> ValidationOutcome:
        """Register a trusted in-process adapter result for the normal review pipeline."""

        validation_id, expires_at = self._validated.put(ValidatedUpload(prepared))
        return ValidationOutcome(
            validation_id,
            expires_at,
            PreparationResult(prepared=prepared, issues=prepared.issues),
        )

    def preview(self, validation_id: str) -> PreviewOutcome:
        validated = self._validated.get(validation_id)
        report = reconcile(validated.prepared, self.repository)
        preview_id, expires_at = self._previews.put(PreviewRecord(validated.prepared, report))
        return PreviewOutcome(preview_id, expires_at, validated.prepared, report)

    def commit(self, preview_id: str) -> CommitOutcome:
        preview = self._previews.get(preview_id)
        with self._commit_lock:
            current_revision = self.repository.data_revision()
            if current_revision != preview.report.data_revision:
                self._previews.pop(preview_id)
                raise StalePreview("database changed after preview; validate and preview again")
            duplicate = self.repository.find_import_by_digest(preview.prepared.semantic_sha256)
            if duplicate is not None:
                self._previews.pop(preview_id)
                return CommitOutcome(
                    status="already_imported",
                    import_id=str(duplicate["import_id"]),
                    data_revision=current_revision,
                    course_count=int(str(duplicate["course_count"])),
                    allocation_count=int(str(duplicate["allocation_count"])),
                    backup_created=False,
                )

            import_id = uuid.uuid4().hex
            committed_at = utc_now()
            backup = self.database.create_backup(f"pre-import-{import_id[:8]}")
            try:
                with self.database.transaction() as connection:
                    if self.repository.data_revision(connection) != preview.report.data_revision:
                        raise StalePreview(
                            "database changed after preview; validate and preview again"
                        )
                    self.repository.insert_import_snapshot(
                        connection,
                        import_id=import_id,
                        prepared=preview.prepared,
                        committed_at=committed_at,
                    )
                    offering_ids: dict[int, int] = {}
                    for ordinal, course in enumerate(preview.prepared.snapshot.courses, start=1):
                        offering_id, _ = self.repository.apply_offering_revision(
                            connection,
                            import_id=import_id,
                            course_ordinal=ordinal,
                            campus=preview.prepared.snapshot.campus,
                            offering=course,
                            created_at=committed_at,
                        )
                        offering_ids[ordinal] = offering_id
                    for issue in preview.prepared.issues:
                        course_ordinal, allocation_ordinal = _issue_ordinals(issue)
                        self.repository.insert_warning(
                            connection,
                            import_id=import_id,
                            issue=issue,
                            course_ordinal=course_ordinal,
                            allocation_ordinal=allocation_ordinal,
                        )
                    for event_ordinal, change in enumerate(preview.report.changes, start=1):
                        self.repository.insert_event(
                            connection,
                            import_id=import_id,
                            offering_id=offering_ids.get(change.course_ordinal),
                            course_ordinal=change.course_ordinal,
                            event_type=change.change_type,
                            details=change.to_dict(),
                            event_ordinal=event_ordinal,
                        )
                    new_revision = self.repository.increment_data_revision(connection, committed_at)
            except (sqlite3.Error, StalePreview):
                raise
            self._previews.pop(preview_id)
            return CommitOutcome(
                status="committed",
                import_id=import_id,
                data_revision=new_revision,
                course_count=preview.prepared.course_count,
                allocation_count=preview.prepared.allocation_count,
                backup_created=backup is not None,
            )


def _safe_filename(filename: str) -> str:
    if not filename or filename in {".", ".."}:
        raise UnsafeFilename("a plain upload filename is required")
    if "/" in filename or "\\" in filename or PurePath(filename).name != filename:
        raise UnsafeFilename("upload filename must not contain a path")
    if len(filename) > 255:
        raise UnsafeFilename("upload filename is too long")
    return filename


def _issue_ordinals(issue: ValidationIssue) -> tuple[int | None, int | None]:
    parts = [part for part in issue.path.split("/") if part]
    course_ordinal: int | None = None
    allocation_ordinal: int | None = None
    if len(parts) >= 2 and parts[0] == "courses" and parts[1].isdigit():
        course_ordinal = int(parts[1]) + 1
    if len(parts) >= 4 and parts[2] == "allocations" and parts[3].isdigit():
        allocation_ordinal = int(parts[3]) + 1
    return course_ordinal, allocation_ordinal
