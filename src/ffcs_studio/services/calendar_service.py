"""Calendar contract validation, preview and immutable commit workflow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from ffcs_studio.domain.calendar import (
    AtomicSlot,
    CalendarProfile,
    MeetingKind,
    SourceEvidence,
    VerificationStatus,
    Weekday,
    WeeklyInterval,
)
from ffcs_studio.persistence.calendar_repository import CalendarRepository


class CalendarServiceError(RuntimeError):
    code = "calendar_error"


class CalendarTokenNotFound(CalendarServiceError):
    code = "calendar_token_not_found"


class InvalidCalendar(CalendarServiceError):
    code = "invalid_calendar"


@dataclass(frozen=True, slots=True)
class CalendarIssue:
    level: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class PreparedCalendar:
    contract: dict[str, Any]
    profile: CalendarProfile
    canonical_json: str
    digest: str
    issues: tuple[CalendarIssue, ...]


@dataclass(frozen=True, slots=True)
class TemporaryCalendar:
    prepared: PreparedCalendar
    expires_at: datetime


class CalendarService:
    def __init__(
        self, repository: CalendarRepository, schema: dict[str, Any], *, ttl_seconds: int = 1800
    ) -> None:
        self.repository = repository
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.ttl = timedelta(seconds=ttl_seconds)
        self._validations: dict[str, TemporaryCalendar] = {}
        self._previews: dict[str, TemporaryCalendar] = {}
        self._lock = RLock()

    def validate(self, payload: object) -> dict[str, Any]:
        prepared = self._prepare(payload)
        token = uuid4().hex
        expires = datetime.now(UTC) + self.ttl
        with self._lock:
            self._purge()
            self._validations[token] = TemporaryCalendar(prepared, expires)
        return {
            "valid": True,
            "validation_id": token,
            "expires_at": expires.isoformat(),
            "calendar": _summary(prepared.profile),
            "issues": [asdict(issue) for issue in prepared.issues],
        }

    def preview(self, validation_id: str) -> dict[str, Any]:
        with self._lock:
            self._purge()
            record = self._validations.get(validation_id)
            if record is None:
                raise CalendarTokenNotFound("calendar validation expired or was not found")
            token = uuid4().hex
            expires = datetime.now(UTC) + self.ttl
            self._previews[token] = TemporaryCalendar(record.prepared, expires)
        existing = self.repository.find_by_digest(record.prepared.digest)
        return {
            "preview_id": token,
            "expires_at": expires.isoformat(),
            "calendar": _summary(record.prepared.profile),
            "slot_count": len(record.prepared.profile.slots),
            "interval_count": sum(
                len(slot.intervals) for slot in record.prepared.profile.slots.values()
            ),
            "duplicate_calendar_id": existing,
            "issues": [asdict(issue) for issue in record.prepared.issues],
        }

    def commit(self, preview_id: str, *, make_active: bool = True) -> dict[str, Any]:
        with self._lock:
            self._purge()
            record = self._previews.get(preview_id)
            if record is None:
                raise CalendarTokenNotFound("calendar preview expired or was not found")
        existing = self.repository.find_by_digest(record.prepared.digest)
        calendar_id = self.repository.commit(
            profile=record.prepared.profile,
            schema_version=str(record.prepared.contract["schema_version"]),
            digest=record.prepared.digest,
            canonical_json=record.prepared.canonical_json,
            make_active=make_active,
        )
        with self._lock:
            self._previews.pop(preview_id, None)
        return {
            "status": "already_committed" if existing else "committed",
            "calendar_id": calendar_id,
            "active": make_active,
        }

    def _prepare(self, payload: object) -> PreparedCalendar:
        if not isinstance(payload, dict):
            raise InvalidCalendar("calendar document must be a JSON object")
        contract, compatibility_issues = _upgrade_v1(payload)
        errors = sorted(self.validator.iter_errors(contract), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            path = "/" + "/".join(str(item) for item in first.path)
            raise InvalidCalendar(f"{path or '/'}: {first.message}")
        evidence_value = contract["evidence"]
        evidence = SourceEvidence(
            evidence_value["kind"],
            evidence_value["reference"],
            evidence_value.get("reviewed_by"),
            evidence_value.get("reviewed_at"),
            evidence_value.get("notes"),
        )
        requested = VerificationStatus(contract["verification_status"])
        issues = list(compatibility_issues)
        if (
            requested is VerificationStatus.OFFICIAL_VERIFIED
            and not evidence.supports_official_verification
        ):
            requested = VerificationStatus.USER_SUPPLIED
            issues.append(
                CalendarIssue(
                    "warning",
                    "official_claim_not_verified",
                    "/verification_status",
                    "The official_verified claim was downgraded because reviewed official "
                    "evidence is absent.",
                )
            )
        slots: dict[str, AtomicSlot] = {}
        for code, values in contract["slots"].items():
            intervals = tuple(
                WeeklyInterval(
                    Weekday(value["day"]),
                    value["start_minute"],
                    value["end_minute"],
                    MeetingKind(value["kind"]),
                    value.get("session_id"),
                )
                for value in values
            )
            slots[code] = AtomicSlot(code, intervals)
        canonical_contract = dict(contract)
        canonical_contract["verification_status"] = requested.value
        canonical = json.dumps(
            canonical_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        profile = CalendarProfile(
            calendar_id=str(uuid4()),
            campus=contract["campus"],
            semester_label=contract["semester_label"],
            profile_name=contract["profile_name"],
            version=1,
            timezone=contract["timezone"],
            verification_status=requested,
            evidence=evidence,
            slots=slots,
        )
        return PreparedCalendar(canonical_contract, profile, canonical, digest, tuple(issues))

    def _purge(self) -> None:
        now = datetime.now(UTC)
        for store in (self._validations, self._previews):
            expired = [key for key, value in store.items() if value.expires_at <= now]
            for key in expired:
                store.pop(key, None)


def _upgrade_v1(payload: dict[str, Any]) -> tuple[dict[str, Any], tuple[CalendarIssue, ...]]:
    if payload.get("schema_version") != "1.0.0":
        return dict(payload), ()
    upgraded = dict(payload)
    upgraded["schema_version"] = "2.0.0"
    upgraded["profile_name"] = "Imported legacy calendar"
    upgraded["evidence"] = {
        "kind": "legacy_unreviewed",
        "reference": str(payload.get("source_reference", "Legacy v1 calendar")),
    }
    upgraded.pop("source_reference", None)
    issue = CalendarIssue(
        "warning",
        "legacy_v1_upgraded",
        "/schema_version",
        "Calendar v1 was read through the compatibility adapter; evidence remains unreviewed.",
    )
    return upgraded, (issue,)


def _summary(profile: CalendarProfile) -> dict[str, Any]:
    return {
        "calendar_id": profile.calendar_id,
        "campus": profile.campus,
        "semester_label": profile.semester_label,
        "profile_name": profile.profile_name,
        "verification_status": profile.verification_status.value,
        "evidence_kind": profile.evidence.kind,
    }
