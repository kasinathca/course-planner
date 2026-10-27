"""Flattened VTOP CSV adapter with explicit provenance metadata."""

from __future__ import annotations

import csv
import io
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ffcs_studio.domain.models import (
    ImportSnapshot,
    RawVtopAllocationRow,
    SemesterOffering,
)
from ffcs_studio.importers.models import (
    PreparationResult,
    build_prepared_import,
)
from ffcs_studio.validation import ValidationIssue

CSV_COLUMNS = (
    "semester_label",
    "category",
    "course_code",
    "course_title",
    "source_row",
    "slot",
    "venue",
    "faculty",
    "course_type",
)


@dataclass(frozen=True, slots=True)
class CsvMetadata:
    campus: str
    semester_label: str
    captured_at: str
    metadata_origin: str = "user_supplied"
    source_kind: str = "manual-csv-upload"
    zero_allocation_courses: tuple[tuple[str, str, str], ...] = ()


def csv_metadata_from_mapping(
    mapping: dict[str, Any],
    *,
    origin: str = "sidecar",
) -> tuple[CsvMetadata | None, tuple[ValidationIssue, ...]]:
    issues: list[ValidationIssue] = []
    for key in ("campus", "semester_label", "captured_at"):
        value = mapping.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_csv_metadata",
                    f"/metadata/{key}",
                    f"{key} is required",
                )
            )
    captured_at = mapping.get("captured_at")
    if isinstance(captured_at, str) and captured_at.strip() and not _is_datetime(captured_at):
        issues.append(
            ValidationIssue(
                "error",
                "invalid_csv_metadata",
                "/metadata/captured_at",
                "captured_at must be an ISO 8601 date-time with timezone",
            )
        )
    zero_courses: list[tuple[str, str, str]] = []
    raw_zero = mapping.get("zero_allocation_courses", [])
    if not isinstance(raw_zero, list):
        issues.append(
            ValidationIssue(
                "error",
                "invalid_csv_metadata",
                "/metadata/zero_allocation_courses",
                "zero_allocation_courses must be an array",
            )
        )
    else:
        for index, course in enumerate(raw_zero):
            if not isinstance(course, dict):
                issues.append(
                    ValidationIssue(
                        "error",
                        "invalid_csv_metadata",
                        f"/metadata/zero_allocation_courses/{index}",
                        "course must be an object",
                    )
                )
                continue
            values = tuple(course.get(key) for key in ("category", "course_code", "course_title"))
            if not all(isinstance(value, str) and value.strip() for value in values):
                issues.append(
                    ValidationIssue(
                        "error",
                        "invalid_csv_metadata",
                        f"/metadata/zero_allocation_courses/{index}",
                        "category, course_code and course_title are required",
                    )
                )
                continue
            zero_courses.append((values[0], values[1], values[2]))  # type: ignore[arg-type]
    if issues:
        return None, tuple(issues)
    return (
        CsvMetadata(
            campus=mapping["campus"],
            semester_label=mapping["semester_label"],
            captured_at=mapping["captured_at"],
            metadata_origin=origin,
            zero_allocation_courses=tuple(zero_courses),
        ),
        (),
    )


def csv_metadata_from_bytes(
    content: bytes,
) -> tuple[CsvMetadata | None, tuple[ValidationIssue, ...]]:
    try:
        decoded = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, (ValidationIssue("error", "invalid_metadata_sidecar", "/metadata", str(exc)),)
    if not isinstance(decoded, dict):
        return None, (
            ValidationIssue(
                "error",
                "invalid_metadata_sidecar",
                "/metadata",
                "sidecar must be an object",
            ),
        )
    return csv_metadata_from_mapping(decoded, origin="sidecar")


def prepare_csv_bytes(
    content: bytes,
    *,
    filename: str,
    metadata: CsvMetadata | None,
) -> PreparationResult:
    issues: list[ValidationIssue] = []
    if metadata is None:
        issues.append(
            ValidationIssue(
                "error",
                "missing_csv_metadata",
                "/metadata",
                "CSV import requires campus, semester_label and captured_at",
            )
        )
        return PreparationResult(None, tuple(issues))
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return PreparationResult(
            None,
            (ValidationIssue("error", "invalid_encoding", "/", str(exc)),),
        )
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = reader.fieldnames
    if headers is None or len(headers) != len(set(headers)) or set(headers) != set(CSV_COLUMNS):
        return PreparationResult(
            None,
            (
                ValidationIssue(
                    "error",
                    "invalid_csv_headers",
                    "/headers",
                    "CSV headers must exactly match the documented flattened contract",
                ),
            ),
        )

    grouped: OrderedDict[tuple[str, str, str], list[RawVtopAllocationRow]] = OrderedDict()
    for line_number, row in enumerate(reader, start=2):
        if row.get(None):
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_csv_row",
                    f"/rows/{line_number}",
                    "row has more values than headers",
                )
            )
            continue
        if all(value is None or value == "" for value in row.values()):
            continue
        path = f"/rows/{line_number}"
        missing = [
            column
            for column in CSV_COLUMNS
            if not isinstance(row.get(column), str) or not row[column].strip()
        ]
        if missing:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_csv_row",
                    path,
                    f"missing non-empty values: {', '.join(missing)}",
                )
            )
            continue
        if row["semester_label"] != metadata.semester_label:
            issues.append(
                ValidationIssue(
                    "error",
                    "conflicting_csv_metadata",
                    f"{path}/semester_label",
                    "row semester_label does not match supplied metadata",
                )
            )
            continue
        try:
            source_row = int(row["source_row"])
            if source_row < 1:
                raise ValueError
        except ValueError:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_csv_row",
                    f"{path}/source_row",
                    "source_row must be a positive integer",
                )
            )
            continue
        key = (row["category"], row["course_code"], row["course_title"])
        grouped.setdefault(key, []).append(
            RawVtopAllocationRow(
                source_row=source_row,
                slot=row["slot"],
                venue=row["venue"],
                faculty=row["faculty"],
                course_type=row["course_type"],
            )
        )
    if any(issue.level == "error" for issue in issues):
        return PreparationResult(None, tuple(issues))

    for key in metadata.zero_allocation_courses:
        grouped.setdefault(key, [])
    courses = tuple(
        SemesterOffering(
            category=key[0],
            course_code=key[1],
            course_title=key[2],
            semester_label=metadata.semester_label,
            allocations=tuple(rows),
        )
        for key, rows in grouped.items()
    )
    snapshot = ImportSnapshot(
        schema_version="csv-1.0.0",
        source=metadata.source_kind,
        campus=metadata.campus,
        semester_label=metadata.semester_label,
        captured_at=metadata.captured_at,
        courses=courses,
    )
    prepared = build_prepared_import(
        source_format="csv",
        source_kind=metadata.source_kind,
        metadata_origin=metadata.metadata_origin,
        filename=filename,
        raw_bytes=content,
        snapshot=snapshot,
        issues=tuple(issues),
    )
    return PreparationResult(prepared, prepared.issues)


def _is_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
