"""SQLite persistence for immutable calendar versions and pairing evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ffcs_studio.domain.calendar import (
    AtomicSlot,
    CalendarProfile,
    MeetingKind,
    SourceEvidence,
    VerificationStatus,
    Weekday,
    WeeklyInterval,
)
from ffcs_studio.domain.component_rules import PairingState
from ffcs_studio.persistence.database import Database


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CalendarRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def find_by_digest(self, digest: str) -> str | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT calendar_id FROM calendar_versions WHERE semantic_sha256 = ?", (digest,)
            ).fetchone()
        return str(row[0]) if row else None

    def commit(
        self,
        *,
        profile: CalendarProfile,
        schema_version: str,
        digest: str,
        canonical_json: str,
        make_active: bool,
    ) -> str:
        existing = self.find_by_digest(digest)
        if existing is not None:
            if make_active:
                self.select_active(existing)
            return existing
        now = utc_now()
        profile_id = str(uuid4())
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT profile_id FROM calendar_profiles WHERE campus = ? AND semester_label = ? "
                "AND profile_name = ?",
                (profile.campus, profile.semester_label, profile.profile_name),
            ).fetchone()
            if row:
                profile_id = str(row[0])
            else:
                connection.execute(
                    "INSERT INTO calendar_profiles(profile_id, campus, semester_label, "
                    "profile_name, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        profile_id,
                        profile.campus,
                        profile.semester_label,
                        profile.profile_name,
                        now,
                    ),
                )
            next_version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM calendar_versions "
                    "WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO calendar_versions(calendar_id, profile_id, version, schema_version, "
                "timezone, verification_status, evidence_kind, evidence_reference, reviewed_by, "
                "reviewed_at, evidence_notes, semantic_sha256, canonical_json, committed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    profile.calendar_id,
                    profile_id,
                    next_version,
                    schema_version,
                    profile.timezone,
                    profile.verification_status.value,
                    profile.evidence.kind,
                    profile.evidence.reference,
                    profile.evidence.reviewed_by,
                    profile.evidence.reviewed_at,
                    profile.evidence.notes,
                    digest,
                    canonical_json,
                    now,
                ),
            )
            for slot_ordinal, slot in enumerate(profile.slots.values(), start=1):
                cursor = connection.execute(
                    "INSERT INTO calendar_atomic_slots(calendar_id, slot_code, slot_ordinal) "
                    "VALUES (?, ?, ?)",
                    (profile.calendar_id, slot.code, slot_ordinal),
                )
                if cursor.lastrowid is None:
                    raise sqlite3.IntegrityError("atomic slot insert returned no identifier")
                for interval_ordinal, interval in enumerate(slot.intervals, start=1):
                    connection.execute(
                        "INSERT INTO calendar_intervals(atomic_slot_id, interval_ordinal, "
                        "weekday, start_minute, end_minute, meeting_kind, session_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            cursor.lastrowid,
                            interval_ordinal,
                            int(interval.day),
                            interval.start_minute,
                            interval.end_minute,
                            interval.kind.value,
                            interval.session_id,
                        ),
                    )
            connection.execute(
                "INSERT INTO calendar_audit_events(calendar_id, event_type, details_json, "
                "created_at) VALUES (?, 'committed', ?, ?)",
                (profile.calendar_id, json.dumps({"make_active": make_active}), now),
            )
            if make_active:
                self._select_active(connection, profile.calendar_id, now)
        return profile.calendar_id

    def select_active(self, calendar_id: str) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM calendar_versions WHERE calendar_id = ?", (calendar_id,)
            ).fetchone()
            if row is None:
                return False
            self._select_active(connection, calendar_id, utc_now())
        return True

    def _select_active(
        self, connection: sqlite3.Connection, calendar_id: str, selected_at: str
    ) -> None:
        identity = connection.execute(
            "SELECT p.campus, p.semester_label FROM calendar_versions v "
            "JOIN calendar_profiles p ON p.profile_id = v.profile_id "
            "WHERE v.calendar_id = ?",
            (calendar_id,),
        ).fetchone()
        if identity is None:
            raise LookupError("calendar not found")
        connection.execute(
            "INSERT INTO active_calendars(campus, semester_label, calendar_id, selected_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(campus, semester_label) DO UPDATE SET "
            "calendar_id = excluded.calendar_id, selected_at = excluded.selected_at",
            (identity["campus"], identity["semester_label"], calendar_id, selected_at),
        )
        connection.execute(
            "INSERT INTO calendar_audit_events(calendar_id, event_type, details_json, "
            "created_at) VALUES (?, 'selected', '{}', ?)",
            (calendar_id, selected_at),
        )

    def list(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT v.calendar_id, p.campus, p.semester_label, p.profile_name, v.version, "
                "v.schema_version, v.verification_status, v.evidence_kind, "
                "v.evidence_reference, v.committed_at, "
                "CASE WHEN a.calendar_id = v.calendar_id THEN 1 ELSE 0 END AS active, "
                "(SELECT COUNT(*) FROM calendar_atomic_slots s WHERE s.calendar_id = "
                "v.calendar_id) AS slot_count FROM calendar_versions v "
                "JOIN calendar_profiles p ON p.profile_id = v.profile_id "
                "LEFT JOIN active_calendars a ON a.calendar_id = v.calendar_id "
                "ORDER BY p.semester_label DESC, p.profile_name, v.version DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, calendar_id: str) -> CalendarProfile | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT v.*, p.campus, p.semester_label, p.profile_name FROM calendar_versions v "
                "JOIN calendar_profiles p ON p.profile_id = v.profile_id "
                "WHERE v.calendar_id = ?",
                (calendar_id,),
            ).fetchone()
            if row is None:
                return None
            slots: dict[str, AtomicSlot] = {}
            slot_rows = connection.execute(
                "SELECT atomic_slot_id, slot_code FROM calendar_atomic_slots "
                "WHERE calendar_id = ? ORDER BY slot_ordinal",
                (calendar_id,),
            ).fetchall()
            for slot_row in slot_rows:
                intervals = tuple(
                    WeeklyInterval(
                        Weekday(item["weekday"]),
                        int(item["start_minute"]),
                        int(item["end_minute"]),
                        MeetingKind(item["meeting_kind"]),
                        item["session_id"],
                    )
                    for item in connection.execute(
                        "SELECT weekday, start_minute, end_minute, meeting_kind, session_id "
                        "FROM calendar_intervals WHERE atomic_slot_id = ? "
                        "ORDER BY interval_ordinal",
                        (slot_row["atomic_slot_id"],),
                    )
                )
                slots[str(slot_row["slot_code"])] = AtomicSlot(
                    str(slot_row["slot_code"]), intervals
                )
        return CalendarProfile(
            calendar_id=str(row["calendar_id"]),
            campus=str(row["campus"]),
            semester_label=str(row["semester_label"]),
            profile_name=str(row["profile_name"]),
            version=int(row["version"]),
            timezone=str(row["timezone"]),
            verification_status=VerificationStatus(row["verification_status"]),
            evidence=SourceEvidence(
                str(row["evidence_kind"]),
                str(row["evidence_reference"]),
                row["reviewed_by"],
                row["reviewed_at"],
                row["evidence_notes"],
            ),
            slots=slots,
        )

    def active_for(self, campus: str, semester_label: str) -> CalendarProfile | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT calendar_id FROM active_calendars WHERE campus = ? AND semester_label = ?",
                (campus, semester_label),
            ).fetchone()
        return self.get(str(row[0])) if row else None

    def pairing_states(self, revision_id: int) -> dict[frozenset[int], PairingState]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT left_allocation_id, right_allocation_id, pairing_state FROM "
                "component_pairing_rules WHERE offering_revision_id = ? "
                "AND invalidated_at IS NULL",
                (revision_id,),
            ).fetchall()
        return {
            frozenset(
                (int(row["left_allocation_id"]), int(row["right_allocation_id"]))
            ): PairingState(row["pairing_state"])
            for row in rows
        }
