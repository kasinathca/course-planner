"""Canonical VTOP JSON v1 adapter."""

from __future__ import annotations

from ffcs_studio.importers.models import (
    PreparationResult,
    build_prepared_import,
)
from ffcs_studio.validation import load_validated_snapshot, validate_json_bytes


def prepare_json_bytes(content: bytes, *, filename: str) -> PreparationResult:
    report = validate_json_bytes(content, source_name=filename)
    if not report.valid:
        return PreparationResult(None, report.issues)
    snapshot = load_validated_snapshot(report)
    prepared = build_prepared_import(
        source_format="json",
        source_kind=snapshot.source,
        metadata_origin="embedded_vtop_json",
        filename=filename,
        raw_bytes=content,
        snapshot=snapshot,
        issues=report.issues,
    )
    return PreparationResult(prepared, prepared.issues)
