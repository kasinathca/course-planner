"""Shared import preparation records and deterministic digests."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256

from ffcs_studio.domain.models import ImportSnapshot, SemesterOffering
from ffcs_studio.validation import ValidationIssue


@dataclass(frozen=True, slots=True)
class PreparedImport:
    source_format: str
    source_kind: str
    metadata_origin: str
    original_filename: str
    raw_sha256: str
    semantic_sha256: str
    canonical_json: str
    snapshot: ImportSnapshot
    issues: tuple[ValidationIssue, ...]

    @property
    def course_count(self) -> int:
        return len(self.snapshot.courses)

    @property
    def allocation_count(self) -> int:
        return self.snapshot.allocation_count


@dataclass(frozen=True, slots=True)
class PreparationResult:
    prepared: PreparedImport | None
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return self.prepared is not None and not any(
            issue.level == "error" for issue in self.issues
        )


def build_prepared_import(
    *,
    source_format: str,
    source_kind: str,
    metadata_origin: str,
    filename: str,
    raw_bytes: bytes,
    snapshot: ImportSnapshot,
    issues: tuple[ValidationIssue, ...] = (),
) -> PreparedImport:
    review_issues = _source_review_issues(snapshot, issues)
    canonical_json = json.dumps(
        snapshot.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return PreparedImport(
        source_format=source_format,
        source_kind=source_kind,
        metadata_origin=metadata_origin,
        original_filename=filename,
        raw_sha256=sha256(raw_bytes).hexdigest(),
        semantic_sha256=sha256(canonical_json.encode("utf-8")).hexdigest(),
        canonical_json=canonical_json,
        snapshot=snapshot,
        issues=review_issues,
    )


def offering_digest(offering: SemesterOffering) -> str:
    content = json.dumps(
        offering.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(content.encode("utf-8")).hexdigest()


def row_digest(values: tuple[object, ...]) -> str:
    content = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return sha256(content.encode("utf-8")).hexdigest()


def _source_review_issues(
    snapshot: ImportSnapshot,
    initial: tuple[ValidationIssue, ...],
) -> tuple[ValidationIssue, ...]:
    issues = list(initial)
    known_paths = {(issue.code, issue.path) for issue in issues}
    identities: Counter[tuple[str, str]] = Counter()
    for course_index, course in enumerate(snapshot.courses):
        identity = (course.category, course.course_code)
        identities[identity] += 1
        source_rows = Counter(row.source_row for row in course.allocations)
        content_seen: Counter[tuple[object, ...]] = Counter()
        for row_index, row in enumerate(course.allocations):
            path = f"/courses/{course_index}/allocations/{row_index}"
            if source_rows[row.source_row] > 1:
                key = ("duplicate_source_row", f"{path}/source_row")
                if key not in known_paths:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            key[0],
                            key[1],
                            (
                                f"source_row {row.source_row} occurs more than once; "
                                "all rows are preserved"
                            ),
                        )
                    )
                    known_paths.add(key)
            content = (row.source_row, row.slot, row.venue, row.faculty, row.course_type)
            content_seen[content] += 1
            if content_seen[content] > 1:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "duplicate_looking_allocation",
                        path,
                        "allocation duplicates earlier source details; both rows are preserved",
                    )
                )
            if row.known_component_type is None:
                key = ("unknown_component_type", f"{path}/course_type")
                if key not in known_paths:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            key[0],
                            key[1],
                            f"unrecognized component type {row.course_type!r}; value is preserved",
                        )
                    )
                    known_paths.add(key)
    for course_index, course in enumerate(snapshot.courses):
        if identities[(course.category, course.course_code)] > 1:
            issues.append(
                ValidationIssue(
                    "warning",
                    "duplicate_course_identity",
                    f"/courses/{course_index}",
                    (
                        "course category/code occurs more than once in this capture; "
                        "revisions remain distinct"
                    ),
                )
            )
    return tuple(issues)
