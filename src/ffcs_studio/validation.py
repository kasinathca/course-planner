"""Versioned JSON Schema validation and safe canonical loading."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from ffcs_studio.domain.models import ImportSnapshot, KnownComponentType


class ValidationSetupError(RuntimeError):
    """Raised when the validator schema itself cannot be loaded."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    level: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    path: Path
    issues: tuple[ValidationIssue, ...]
    document: Mapping[str, Any] | None = None

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors


def default_vtop_schema_path() -> Path:
    """Return the schema installed inside the application package."""

    schema = resources.files("ffcs_studio.resources.schemas").joinpath("vtop-export.schema.json")
    return Path(str(schema))


def _json_pointer(parts: Iterable[object]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _load_schema(path: Path) -> Mapping[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationSetupError(f"cannot load schema {path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValidationSetupError(f"schema {path} must contain a JSON object")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValidationSetupError(f"invalid schema {path}: {exc.message}") from exc
    return schema


def _semantic_warnings(document: Mapping[str, Any]) -> list[ValidationIssue]:
    warnings: list[ValidationIssue] = []
    known = {member.value for member in KnownComponentType}
    courses = document.get("courses")
    if not isinstance(courses, list):
        return warnings
    for course_index, course in enumerate(courses):
        if not isinstance(course, dict) or not isinstance(course.get("allocations"), list):
            continue
        for row_index, row in enumerate(course["allocations"]):
            if not isinstance(row, dict):
                continue
            raw_type = row.get("course_type")
            if isinstance(raw_type, str) and raw_type.strip().upper() not in known:
                warnings.append(
                    ValidationIssue(
                        level="warning",
                        code="unknown_component_type",
                        path=f"/courses/{course_index}/allocations/{row_index}/course_type",
                        message=(
                            f"unrecognized component type {raw_type!r}; "
                            "value is preserved for review"
                        ),
                    )
                )
    return warnings


def validate_json_bytes(
    content: bytes,
    *,
    source_name: str = "uploaded.json",
    schema_path: Path | None = None,
) -> ValidationReport:
    """Decode and validate bounded JSON bytes using the canonical schema."""

    path = Path(source_name)
    try:
        decoded = json.loads(content.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        issue = ValidationIssue("error", "invalid_encoding", "/", str(exc))
        return ValidationReport(path=path, issues=(issue,))
    except json.JSONDecodeError as exc:
        issue = ValidationIssue(
            "error",
            "invalid_json",
            "/",
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
        return ValidationReport(path=path, issues=(issue,))

    if not isinstance(decoded, dict):
        issue = ValidationIssue("error", "invalid_root", "/", "document must be a JSON object")
        return ValidationReport(path=path, issues=(issue,))
    return validate_mapping(decoded, source_name=source_name, schema_path=schema_path)


def validate_mapping(
    decoded: Mapping[str, Any],
    *,
    source_name: str = "document",
    schema_path: Path | None = None,
) -> ValidationReport:
    """Validate an already decoded mapping with identical CLI/upload semantics."""

    schema = _load_schema(schema_path or default_vtop_schema_path())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(decoded), key=lambda error: list(error.absolute_path))
    issues = [
        ValidationIssue(
            level="error",
            code=f"schema_{error.validator}",
            path=_json_pointer(error.absolute_path),
            message=error.message,
        )
        for error in errors
    ]
    if not errors:
        issues.extend(_semantic_warnings(decoded))
    return ValidationReport(path=Path(source_name), issues=tuple(issues), document=decoded)


def validate_json_file(
    input_path: Path,
    *,
    schema_path: Path | None = None,
) -> ValidationReport:
    """Validate one JSON file through the same byte-oriented upload path."""

    try:
        content = input_path.read_bytes()
    except OSError as exc:
        issue = ValidationIssue("error", "file_error", "/", str(exc))
        return ValidationReport(path=input_path, issues=(issue,))
    report = validate_json_bytes(
        content,
        source_name=str(input_path),
        schema_path=schema_path,
    )
    return ValidationReport(path=input_path, issues=report.issues, document=report.document)


def load_validated_snapshot(report: ValidationReport) -> ImportSnapshot:
    """Create a domain snapshot only after successful schema validation."""

    if not report.valid or report.document is None:
        raise ValueError("cannot load an invalid validation report")
    return ImportSnapshot.from_mapping(report.document)


def summarize_report(report: ValidationReport) -> Sequence[str]:
    if report.valid and report.document is not None:
        snapshot = load_validated_snapshot(report)
        lines = [
            f"OK {report.path}: {len(snapshot.courses)} course(s), "
            f"{snapshot.allocation_count} allocation row(s)",
        ]
    else:
        lines = [f"INVALID {report.path}: {len(report.errors)} error(s)"]
    lines.extend(
        f"{issue.level.upper()} {issue.code} {issue.path}: {issue.message}"
        for issue in report.issues
    )
    return lines
