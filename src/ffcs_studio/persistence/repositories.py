"""Typed, parameterized SQLite repositories for import and course data."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from ffcs_studio.domain.models import RawVtopAllocationRow, SemesterOffering
from ffcs_studio.importers.models import PreparedImport, offering_digest, row_digest
from ffcs_studio.persistence.database import Database
from ffcs_studio.validation import ValidationIssue


class PaginatedResult(TypedDict):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class OfferingKey:
    campus: str
    semester_label: str
    category: str
    course_code: str


@dataclass(frozen=True, slots=True)
class StoredAllocation:
    allocation_ordinal: int
    source_row: int
    slot: str
    venue: str
    faculty: str
    course_type: str

    @property
    def signature(self) -> tuple[object, ...]:
        return (self.source_row, self.slot, self.venue, self.faculty, self.course_type)


@dataclass(frozen=True, slots=True)
class StoredOffering:
    offering_id: int
    revision_id: int
    import_id: str
    key: OfferingKey
    course_title: str
    allocations: tuple[StoredAllocation, ...]


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def data_revision(self, connection: sqlite3.Connection | None = None) -> int:
        if connection is not None:
            row = connection.execute(
                "SELECT data_revision FROM app_state WHERE singleton_id = 1"
            ).fetchone()
            return int(row[0])
        with self.database.connection() as current:
            return self.data_revision(current)

    def find_import_by_digest(
        self,
        semantic_sha256: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, object] | None:
        if connection is None:
            with self.database.connection() as current:
                return self.find_import_by_digest(semantic_sha256, current)
        row = connection.execute(
            "SELECT import_id, committed_at, course_count, allocation_count "
            "FROM import_snapshots WHERE semantic_sha256 = ?",
            (semantic_sha256,),
        ).fetchone()
        return dict(row) if row is not None else None

    def active_offering(
        self,
        key: OfferingKey,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOffering | None:
        if connection is None:
            with self.database.connection() as current:
                return self.active_offering(key, current)
        row = connection.execute(
            "SELECT o.offering_id, o.active_revision_id, r.import_id, r.raw_course_title "
            "FROM offerings o "
            "JOIN offering_revisions r ON r.revision_id = o.active_revision_id "
            "WHERE o.campus = ? AND o.semester_label = ? AND o.category = ? "
            "AND o.course_code = ?",
            (key.campus, key.semester_label, key.category, key.course_code),
        ).fetchone()
        if row is None:
            return None
        allocations = tuple(
            StoredAllocation(
                allocation_ordinal=int(item["allocation_ordinal"]),
                source_row=int(item["source_row"]),
                slot=str(item["raw_slot"]),
                venue=str(item["raw_venue"]),
                faculty=str(item["raw_faculty"]),
                course_type=str(item["raw_course_type"]),
            )
            for item in connection.execute(
                "SELECT allocation_ordinal, source_row, raw_slot, raw_venue, raw_faculty, "
                "raw_course_type FROM allocation_rows WHERE revision_id = ? "
                "ORDER BY allocation_ordinal",
                (row["active_revision_id"],),
            )
        )
        return StoredOffering(
            offering_id=int(row["offering_id"]),
            revision_id=int(row["active_revision_id"]),
            import_id=str(row["import_id"]),
            key=key,
            course_title=str(row["raw_course_title"]),
            allocations=allocations,
        )

    def insert_import_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        import_id: str,
        prepared: PreparedImport,
        committed_at: str,
    ) -> None:
        snapshot = prepared.snapshot
        connection.execute(
            "INSERT INTO import_snapshots("
            "import_id, source_format, source_kind, metadata_origin, original_filename, "
            "raw_sha256, semantic_sha256, campus, semester_label, captured_at, course_count, "
            "allocation_count, canonical_json, committed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                import_id,
                prepared.source_format,
                prepared.source_kind,
                prepared.metadata_origin,
                prepared.original_filename,
                prepared.raw_sha256,
                prepared.semantic_sha256,
                snapshot.campus,
                snapshot.semester_label,
                snapshot.captured_at,
                prepared.course_count,
                prepared.allocation_count,
                prepared.canonical_json,
                committed_at,
            ),
        )

    def apply_offering_revision(
        self,
        connection: sqlite3.Connection,
        *,
        import_id: str,
        course_ordinal: int,
        campus: str,
        offering: SemesterOffering,
        created_at: str,
    ) -> tuple[int, int]:
        course_id = self._get_or_create_course(connection, offering, created_at)
        key = OfferingKey(
            campus=campus,
            semester_label=offering.semester_label,
            category=offering.category,
            course_code=offering.course_code,
        )
        offering_id = self._get_or_create_offering(connection, key, course_id, created_at)
        cursor = connection.execute(
            "INSERT INTO offering_revisions("
            "offering_id, import_id, course_id, course_ordinal, raw_category, raw_course_code, "
            "raw_course_title, revision_sha256, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                offering_id,
                import_id,
                course_id,
                course_ordinal,
                offering.category,
                offering.course_code,
                offering.course_title,
                offering_digest(offering),
                created_at,
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.IntegrityError("offering revision insert returned no identifier")
        revision_id = cursor.lastrowid
        for allocation_ordinal, row in enumerate(offering.allocations, start=1):
            self._insert_allocation(connection, revision_id, allocation_ordinal, row)
        connection.execute(
            "UPDATE offerings SET active_course_id = ?, active_revision_id = ?, updated_at = ? "
            "WHERE offering_id = ?",
            (course_id, revision_id, created_at, offering_id),
        )
        return offering_id, revision_id

    def insert_warning(
        self,
        connection: sqlite3.Connection,
        *,
        import_id: str,
        issue: ValidationIssue,
        course_ordinal: int | None,
        allocation_ordinal: int | None,
    ) -> None:
        connection.execute(
            "INSERT INTO import_warnings("
            "import_id, course_ordinal, allocation_ordinal, warning_code, json_path, message"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                import_id,
                course_ordinal,
                allocation_ordinal,
                issue.code,
                issue.path,
                issue.message,
            ),
        )

    def insert_event(
        self,
        connection: sqlite3.Connection,
        *,
        import_id: str,
        offering_id: int | None,
        course_ordinal: int,
        event_type: str,
        details: dict[str, object],
        event_ordinal: int,
    ) -> None:
        connection.execute(
            "INSERT INTO reconciliation_events("
            "import_id, offering_id, course_ordinal, event_type, detail_json, event_ordinal"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                import_id,
                offering_id,
                course_ordinal,
                event_type,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
                event_ordinal,
            ),
        )

    def increment_data_revision(self, connection: sqlite3.Connection, updated_at: str) -> int:
        connection.execute(
            "UPDATE app_state SET data_revision = data_revision + 1, updated_at = ? "
            "WHERE singleton_id = 1",
            (updated_at,),
        )
        return self.data_revision(connection)

    def list_imports(self, *, page: int, page_size: int) -> PaginatedResult:
        offset = (page - 1) * page_size
        with self.database.connection() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM import_snapshots").fetchone()[0])
            rows = connection.execute(
                "SELECT import_id, source_format, source_kind, original_filename, campus, "
                "semester_label, captured_at, course_count, allocation_count, committed_at "
                "FROM import_snapshots ORDER BY committed_at DESC, import_id LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def import_detail(self, import_id: str) -> dict[str, object] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT import_id, source_format, source_kind, metadata_origin, original_filename, "
                "raw_sha256, semantic_sha256, campus, semester_label, captured_at, course_count, "
                "allocation_count, committed_at FROM import_snapshots WHERE import_id = ?",
                (import_id,),
            ).fetchone()
            if row is None:
                return None
            warnings = [
                dict(item)
                for item in connection.execute(
                    "SELECT course_ordinal, allocation_ordinal, warning_code AS code, "
                    "json_path AS path, message FROM import_warnings WHERE import_id = ? "
                    "ORDER BY warning_id",
                    (import_id,),
                )
            ]
        result = dict(row)
        result["warnings"] = warnings
        return result

    def import_diff(self, import_id: str) -> list[dict[str, object]] | None:
        with self.database.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM import_snapshots WHERE import_id = ?", (import_id,)
            ).fetchone()
            if exists is None:
                return None
            rows = connection.execute(
                "SELECT offering_id, course_ordinal, event_type, detail_json FROM "
                "reconciliation_events WHERE import_id = ? ORDER BY event_ordinal",
                (import_id,),
            ).fetchall()
        return [
            {
                "offering_id": row["offering_id"],
                "course_ordinal": row["course_ordinal"],
                "event_type": row["event_type"],
                "details": json.loads(row["detail_json"]),
            }
            for row in rows
        ]

    def semesters(self) -> list[dict[str, object]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT campus, semester_label, COUNT(*) AS offering_count FROM offerings "
                "WHERE active_revision_id IS NOT NULL GROUP BY campus, semester_label "
                "ORDER BY semester_label DESC, campus"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_offerings(
        self,
        *,
        campus: str | None,
        semester_label: str | None,
        search: str | None,
        category: str | None,
        component: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResult:
        where = ["o.active_revision_id IS NOT NULL"]
        parameters: list[object] = []
        if campus:
            where.append("o.campus = ?")
            parameters.append(campus)
        if semester_label:
            where.append("o.semester_label = ?")
            parameters.append(semester_label)
        if search:
            where.append("(LOWER(o.course_code) LIKE ? OR LOWER(r.raw_course_title) LIKE ?)")
            term = f"%{search.casefold()}%"
            parameters.extend((term, term))
        if category:
            where.append("o.category = ?")
            parameters.append(category)
        if component:
            where.append(
                "EXISTS (SELECT 1 FROM allocation_rows ax WHERE ax.revision_id = "
                "o.active_revision_id AND ax.component_search = ?)"
            )
            parameters.append(component.casefold())
        clause = " AND ".join(where)
        offset = (page - 1) * page_size
        with self.database.connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM offerings o JOIN offering_revisions r "
                    f"ON r.revision_id = o.active_revision_id WHERE {clause}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT o.offering_id, o.campus, o.semester_label, o.category, o.course_code, "
                "r.raw_course_title AS course_title, r.import_id, "
                "COUNT(a.allocation_id) AS allocation_count, "
                "GROUP_CONCAT(DISTINCT a.raw_course_type) AS component_types "
                "FROM offerings o JOIN offering_revisions r "
                "ON r.revision_id = o.active_revision_id "
                "LEFT JOIN allocation_rows a ON a.revision_id = r.revision_id "
                f"WHERE {clause} GROUP BY o.offering_id "
                "ORDER BY o.course_code, r.raw_course_title, o.category, o.offering_id "
                "LIMIT ? OFFSET ?",
                (*parameters, page_size, offset),
            ).fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            raw_types = item.pop("component_types")
            item["component_types"] = sorted(str(raw_types).split(",")) if raw_types else []
            items.append(item)
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def offering_detail(self, offering_id: int) -> dict[str, object] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT o.offering_id, o.campus, o.semester_label, o.category, o.course_code, "
                "r.raw_course_title AS course_title, r.revision_id, r.import_id, "
                "r.course_ordinal, "
                "i.source_format, i.source_kind, i.metadata_origin, i.original_filename, "
                "i.captured_at, i.committed_at, "
                "(SELECT COUNT(*) FROM allocation_rows a WHERE a.revision_id = r.revision_id) "
                "AS allocation_count FROM offerings o JOIN offering_revisions r "
                "ON r.revision_id = o.active_revision_id JOIN import_snapshots i "
                "ON i.import_id = r.import_id WHERE o.offering_id = ?",
                (offering_id,),
            ).fetchone()
            if row is None:
                return None
            warnings = [
                dict(item)
                for item in connection.execute(
                    "SELECT allocation_ordinal, warning_code AS code, json_path AS path, "
                    "message FROM import_warnings WHERE import_id = ? AND course_ordinal = ? "
                    "ORDER BY warning_id",
                    (row["import_id"], row["course_ordinal"]),
                )
            ]
        result = dict(row)
        result["warnings"] = warnings
        result["missing_metadata"] = ["credits", "curriculum_course_type"]
        return result

    def offering_allocations(self, offering_id: int) -> list[dict[str, object]] | None:
        with self.database.connection() as connection:
            revision = connection.execute(
                "SELECT active_revision_id FROM offerings WHERE offering_id = ?",
                (offering_id,),
            ).fetchone()
            if revision is None or revision[0] is None:
                return None
            rows = connection.execute(
                "SELECT allocation_id, allocation_ordinal, source_row, raw_slot AS slot, "
                "raw_venue AS venue, raw_faculty AS faculty, raw_course_type AS course_type "
                "FROM allocation_rows WHERE revision_id = ? ORDER BY allocation_ordinal",
                (revision[0],),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_or_create_course(
        self,
        connection: sqlite3.Connection,
        offering: SemesterOffering,
        created_at: str,
    ) -> int:
        connection.execute(
            "INSERT OR IGNORE INTO courses("
            "course_code, course_title, code_search, title_search, created_at"
            ") VALUES (?, ?, ?, ?, ?)",
            (
                offering.course_code,
                offering.course_title,
                offering.course_code.casefold(),
                offering.course_title.casefold(),
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT course_id FROM courses WHERE course_code = ? AND course_title = ?",
            (offering.course_code, offering.course_title),
        ).fetchone()
        return int(row[0])

    def _get_or_create_offering(
        self,
        connection: sqlite3.Connection,
        key: OfferingKey,
        course_id: int,
        created_at: str,
    ) -> int:
        connection.execute(
            "INSERT OR IGNORE INTO offerings("
            "campus, semester_label, category, course_code, active_course_id, "
            "created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key.campus,
                key.semester_label,
                key.category,
                key.course_code,
                course_id,
                created_at,
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT offering_id FROM offerings WHERE campus = ? AND semester_label = ? "
            "AND category = ? AND course_code = ?",
            (key.campus, key.semester_label, key.category, key.course_code),
        ).fetchone()
        return int(row[0])

    def _insert_allocation(
        self,
        connection: sqlite3.Connection,
        revision_id: int,
        allocation_ordinal: int,
        row: RawVtopAllocationRow,
    ) -> None:
        signature = (row.source_row, row.slot, row.venue, row.faculty, row.course_type)
        connection.execute(
            "INSERT INTO allocation_rows("
            "revision_id, allocation_ordinal, source_row, raw_slot, raw_venue, raw_faculty, "
            "raw_course_type, slot_search, venue_search, faculty_search, "
            "component_search, row_sha256"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                revision_id,
                allocation_ordinal,
                row.source_row,
                row.slot,
                row.venue,
                row.faculty,
                row.course_type,
                row.slot.casefold(),
                row.venue.casefold(),
                row.faculty.casefold(),
                row.course_type.casefold(),
                row_digest(signature),
            ),
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
