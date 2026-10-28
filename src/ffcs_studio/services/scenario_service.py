"""Scenario source-reference normalization and stale-data diagnostics."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.repositories import Repository


class ScenarioSourceService:
    def __init__(self, repository: Repository, calendars: CalendarRepository) -> None:
        self.repository = repository
        self.calendars = calendars

    def prepare(
        self, document: dict[str, Any], *, solver_ready: bool
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str]:
        normalized = deepcopy(document)
        for course in normalized.get("courses", []):
            detail = self.repository.offering_detail(int(course["offering_id"]))
            if detail is not None and course.get("source_revision_id") is None:
                course["source_revision_id"] = int(str(detail["revision_id"]))
        references = self.source_references(normalized)
        issues = self.compatibility(normalized)
        if any(item["level"] == "error" for item in issues):
            status = "stale"
        elif solver_ready:
            status = "ready"
        else:
            status = "draft"
        return normalized, references, issues, status

    def source_references(self, document: dict[str, Any]) -> dict[str, Any]:
        return {
            "calendar_id": document.get("calendar_id") or None,
            "offerings": [
                {
                    "offering_id": int(course["offering_id"]),
                    "revision_id": course.get("source_revision_id"),
                    "allocation_ids": sorted(
                        {
                            *course.get("locked_allocation_ids", []),
                            *course.get("forbidden_allocation_ids", []),
                        }
                    ),
                }
                for course in document.get("courses", [])
            ],
        }

    def compatibility(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        campus = str(document.get("campus", ""))
        semester = str(document.get("semester_label", ""))
        calendar_id = str(document.get("calendar_id") or "")
        if calendar_id:
            calendar = self.calendars.get(calendar_id)
            if calendar is None:
                issues.append(
                    _issue("error", "calendar_missing", "The saved calendar version is missing")
                )
            elif calendar.campus != campus or calendar.semester_label != semester:
                issues.append(
                    _issue(
                        "error",
                        "calendar_semester_mismatch",
                        "The saved calendar does not match the saved campus and semester",
                    )
                )
            else:
                active = self.calendars.active_for(campus, semester)
                if active is not None and active.calendar_id != calendar_id:
                    issues.append(
                        _issue(
                            "warning",
                            "calendar_not_active",
                            "A newer or different calendar is active; this scenario keeps "
                            "its saved version",
                        )
                    )
        for course in document.get("courses", []):
            offering_id = int(course["offering_id"])
            detail = self.repository.offering_detail(offering_id)
            if detail is None:
                issues.append(
                    _issue(
                        "error",
                        "offering_missing",
                        "A saved course offering is no longer available",
                        offering_id,
                    )
                )
                continue
            if detail["campus"] != campus or detail["semester_label"] != semester:
                issues.append(
                    _issue(
                        "error",
                        "offering_semester_mismatch",
                        "A saved offering belongs to another campus or semester",
                        offering_id,
                    )
                )
            current_revision = int(str(detail["revision_id"]))
            saved_revision = course.get("source_revision_id")
            if saved_revision is not None and int(saved_revision) != current_revision:
                issues.append(
                    {
                        **_issue(
                            "error",
                            "offering_revision_stale",
                            "The active VTOP revision changed; review this course before relinking",
                            offering_id,
                        ),
                        "saved_revision_id": int(saved_revision),
                        "current_revision_id": current_revision,
                    }
                )
                continue
            allocations = self.repository.offering_allocations(offering_id) or []
            available = {int(str(item["allocation_id"])) for item in allocations}
            referenced = {
                *course.get("locked_allocation_ids", []),
                *course.get("forbidden_allocation_ids", []),
            }
            missing = sorted(int(item) for item in referenced if int(item) not in available)
            if missing:
                issues.append(
                    {
                        **_issue(
                            "error",
                            "allocation_reference_missing",
                            "One or more saved allocation locks no longer exist",
                            offering_id,
                        ),
                        "allocation_ids": missing,
                    }
                )
        return issues

    def result_compatibility(self, saved_result: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        calendar_id = str(saved_result["calendar_id"])
        if self.calendars.get(calendar_id) is None:
            issues.append(
                _issue("error", "calendar_missing", "The result's calendar version is missing")
            )
        for course in saved_result["result"].get("course_metadata", []):
            offering_id = int(course["offering_id"])
            detail = self.repository.offering_detail(offering_id)
            if detail is None:
                issues.append(
                    _issue(
                        "error",
                        "offering_missing",
                        "A result offering is no longer active",
                        offering_id,
                    )
                )
            elif int(str(detail["revision_id"])) != int(course["revision_id"]):
                issues.append(
                    _issue(
                        "warning",
                        "result_revision_historical",
                        "This saved result uses a historical offering revision",
                        offering_id,
                    )
                )
        return issues


def _issue(level: str, code: str, message: str, offering_id: int | None = None) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, "offering_id": offering_id}
