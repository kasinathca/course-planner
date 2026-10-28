"""Evidence-aware, semester-specific slot calendar domain types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Any


class Weekday(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class MeetingKind(StrEnum):
    THEORY = "theory"
    LAB = "lab"
    TUTORIAL = "tutorial"
    PROJECT = "project"
    SOFT_SKILLS = "soft_skills"
    OTHER = "other"


class VerificationStatus(StrEnum):
    OFFICIAL_VERIFIED = "official_verified"
    EVIDENCE_SUPPORTED = "evidence_supported"
    DRAFT_UNVERIFIED = "draft_unverified"
    USER_SUPPLIED = "user_supplied"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    kind: str
    reference: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None

    @property
    def supports_official_verification(self) -> bool:
        return (
            self.kind == "official_document"
            and bool(self.reference.strip())
            and bool(self.reviewed_by and self.reviewed_by.strip())
            and bool(self.reviewed_at and self.reviewed_at.strip())
        )


@dataclass(frozen=True, slots=True, order=True)
class WeeklyInterval:
    """A half-open interval [start_minute, end_minute) on one weekday."""

    day: Weekday
    start_minute: int
    end_minute: int
    kind: MeetingKind
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.start_minute < self.end_minute <= 1440:
            raise ValueError("weekly interval must satisfy 0 <= start < end <= 1440")

    @property
    def duration_minutes(self) -> int:
        return self.end_minute - self.start_minute

    def overlaps(self, other: WeeklyInterval) -> bool:
        return (
            self.day == other.day
            and self.start_minute < other.end_minute
            and other.start_minute < self.end_minute
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "day": int(self.day),
            "start_minute": self.start_minute,
            "end_minute": self.end_minute,
            "kind": self.kind.value,
        }
        if self.session_id is not None:
            result["session_id"] = self.session_id
        return result


@dataclass(frozen=True, slots=True)
class AtomicSlot:
    code: str
    intervals: tuple[WeeklyInterval, ...]

    def __post_init__(self) -> None:
        if not self.code.strip() or "+" in self.code:
            raise ValueError("atomic slot code must be non-blank and cannot contain '+'")
        if not self.intervals:
            raise ValueError("atomic slot must contain at least one interval")


@dataclass(frozen=True, slots=True)
class SlotExpressionParseResult:
    raw: str
    tokens: tuple[str, ...]
    error_code: str | None = None
    error_message: str | None = None

    @property
    def valid(self) -> bool:
        return self.error_code is None


def parse_slot_expression(raw: object) -> SlotExpressionParseResult:
    """Tokenize without normalizing away malformed empty components."""

    if not isinstance(raw, str):
        return SlotExpressionParseResult(
            raw="" if raw is None else str(raw),
            tokens=(),
            error_code="invalid_type",
            error_message="slot expression must be a string",
        )
    if not raw.strip():
        return SlotExpressionParseResult(
            raw=raw,
            tokens=(),
            error_code="blank_expression",
            error_message="slot expression cannot be blank",
        )
    parts = raw.split("+")
    if any(not part.strip() for part in parts):
        return SlotExpressionParseResult(
            raw=raw,
            tokens=tuple(part.strip() for part in parts if part.strip()),
            error_code="malformed_expression",
            error_message="slot expression contains an empty token",
        )
    return SlotExpressionParseResult(raw=raw, tokens=tuple(part.strip() for part in parts))


@dataclass(frozen=True, slots=True)
class CalendarProfile:
    calendar_id: str
    campus: str
    semester_label: str
    profile_name: str
    version: int
    timezone: str
    verification_status: VerificationStatus
    evidence: SourceEvidence
    slots: Mapping[str, AtomicSlot]

    def __post_init__(self) -> None:
        for name in ("calendar_id", "campus", "semester_label", "profile_name", "timezone"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be blank")
        if self.version < 1:
            raise ValueError("calendar version must be at least 1")
        if self.timezone != "Asia/Kolkata":
            raise ValueError("Phase 2 supports Asia/Kolkata only")
        if (
            self.verification_status is VerificationStatus.OFFICIAL_VERIFIED
            and not self.evidence.supports_official_verification
        ):
            raise ValueError("official_verified requires reviewed official-document evidence")
        normalized = {code: slot for code, slot in self.slots.items()}
        if not normalized:
            raise ValueError("calendar must contain at least one atomic slot")
        if len(normalized) != len(self.slots):
            raise ValueError("calendar slot codes must be unique")
        object.__setattr__(self, "slots", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class UnresolvedSlot:
    token: str
    reason: str


@dataclass(frozen=True, slots=True)
class SlotResolution:
    raw: str
    tokens: tuple[str, ...]
    intervals: tuple[WeeklyInterval, ...]
    unresolved: tuple[UnresolvedSlot, ...]
    parse_error: str | None = None

    @property
    def resolved(self) -> bool:
        return self.parse_error is None and not self.unresolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "tokens": list(self.tokens),
            "resolved": self.resolved,
            "parse_error": self.parse_error,
            "unresolved": [
                {"token": item.token, "reason": item.reason} for item in self.unresolved
            ],
            "intervals": [interval.to_dict() for interval in self.intervals],
        }
