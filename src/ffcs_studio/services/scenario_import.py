"""Reviewed scenario JSON import tokens; imported flags are never trusted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ffcs_studio.services.import_service import ExpiringStore, TemporaryRecordNotFound


class ScenarioImportError(ValueError):
    code = "scenario_import_error"


@dataclass(frozen=True, slots=True)
class ScenarioImportRecord:
    original_scenario_id: str | None
    original_name: str
    original_description: str
    document: dict[str, Any]
    source_references: dict[str, Any]


class ScenarioImportService:
    def __init__(self) -> None:
        self._validated = ExpiringStore[ScenarioImportRecord](max_entries=20, ttl_seconds=900)
        self._previews = ExpiringStore[ScenarioImportRecord](max_entries=20, ttl_seconds=900)

    def validate(self, payload: dict[str, Any]) -> tuple[str, str, ScenarioImportRecord]:
        if set(payload) != {
            "export_schema_version",
            "kind",
            "scenario",
            "document",
            "source_references",
        }:
            raise ScenarioImportError("Scenario export contains missing or undocumented fields")
        if payload["export_schema_version"] != "1.0" or payload["kind"] != "ffcs-studio-scenario":
            raise ScenarioImportError("Unsupported scenario export kind or version")
        scenario = payload["scenario"]
        if not isinstance(scenario, dict) or not isinstance(payload["document"], dict):
            raise ScenarioImportError("Scenario export fields are malformed")
        allowed = {
            "scenario_id",
            "name",
            "description",
            "current_revision",
            "status",
            "created_at",
            "updated_at",
        }
        if not set(scenario).issubset(allowed):
            raise ScenarioImportError("Scenario metadata contains undocumented fields")
        name = scenario.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ScenarioImportError("Scenario name is missing or invalid")
        description = scenario.get("description", "")
        if not isinstance(description, str) or len(description) > 2000:
            raise ScenarioImportError("Scenario description is invalid")
        references = payload["source_references"]
        if not isinstance(references, dict):
            raise ScenarioImportError("Scenario source references are malformed")
        record = ScenarioImportRecord(
            original_scenario_id=str(scenario["scenario_id"])
            if scenario.get("scenario_id")
            else None,
            original_name=name.strip(),
            original_description=description,
            document=payload["document"],
            source_references=references,
        )
        token, expires = self._validated.put(record)
        return token, expires, record

    def preview(self, validation_id: str) -> tuple[str, str, ScenarioImportRecord]:
        try:
            record = self._validated.get(validation_id)
        except TemporaryRecordNotFound as exc:
            raise ScenarioImportError(str(exc)) from exc
        token, expires = self._previews.put(record)
        return token, expires, record

    def consume(self, preview_id: str) -> ScenarioImportRecord:
        try:
            record = self._previews.get(preview_id)
        except TemporaryRecordNotFound as exc:
            raise ScenarioImportError(str(exc)) from exc
        self._previews.pop(preview_id)
        return record
