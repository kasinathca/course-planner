"""Validated canonical-curriculum and legacy-v6 import adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from ffcs_studio.degree.accounting import parse_milli_credit
from ffcs_studio.degree.models import CatalogueCourse, EvidenceStatus


class DegreeImportError(ValueError):
    """A degree source cannot be imported without review."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def parse_curriculum(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "1.0":
        raise DegreeImportError("curriculum schema_version must be 1.0")
    programme = payload.get("programme")
    courses = payload.get("courses")
    if not isinstance(programme, dict) or not isinstance(courses, list):
        raise DegreeImportError("curriculum requires programme and courses")
    required_programme = ("programme_code", "name", "admission_batch", "revision_code")
    if any(
        not isinstance(programme.get(key), str) or not programme[key].strip()
        for key in required_programme
    ):
        raise DegreeImportError("programme identity fields are required")
    parsed: list[CatalogueCourse] = []
    seen_ids: set[str] = set()
    warnings: list[dict[str, str]] = []
    for index, raw in enumerate(courses):
        if not isinstance(raw, dict):
            raise DegreeImportError(f"courses/{index} must be an object")
        raw_values = (
            raw.get("source_id"),
            raw.get("code"),
            raw.get("title"),
            raw.get("category"),
        )
        if not all(isinstance(value, str) and value.strip() for value in raw_values):
            raise DegreeImportError(
                f"courses/{index} is missing source_id, code, title or category"
            )
        source_id, code, title, category = (str(value) for value in raw_values)
        canonical_id = str(raw.get("canonical_id") or source_id).strip()
        if canonical_id in seen_ids:
            raise DegreeImportError(f"duplicate canonical_id: {canonical_id}")
        seen_ids.add(canonical_id)
        credits = parse_milli_credit(raw.get("credits"))
        unresolved = tuple(str(item) for item in raw.get("unresolved", []) if str(item).strip())
        if credits is None:
            warnings.append(
                {"code": "unknown_credits", "message": f"{code} has no verified credit value."}
            )
        parsed.append(
            CatalogueCourse(
                canonical_id=canonical_id,
                source_id=source_id,
                code=code.strip(),
                title=title.strip(),
                category=category.strip(),
                curriculum_type=str(raw.get("curriculum_type") or "UNKNOWN"),
                total_credits_milli=credits,
                lecture=_optional_int(raw.get("lecture")),
                tutorial=_optional_int(raw.get("tutorial")),
                practical=_optional_int(raw.get("practical")),
                project=_optional_int(raw.get("project")),
                provenance=_evidence(raw.get("provenance", "user_supplied")),
                alternative_group=_optional_text(raw.get("alternative_group")),
                notes=str(raw.get("notes") or ""),
                unresolved=unresolved,
            )
        )
    relationships = payload.get("relationships", [])
    prerequisites = payload.get("prerequisites", [])
    if not isinstance(relationships, list) or not isinstance(prerequisites, list):
        raise DegreeImportError("relationships and prerequisites must be arrays")
    for index, relationship in enumerate(relationships):
        if not isinstance(relationship, dict) or not _string_list(relationship.get("course_ids")):
            raise DegreeImportError(
                f"relationships/{index} requires a non-empty string course_ids array"
            )
    for index, rule in enumerate(prerequisites):
        if not isinstance(rule, dict) or not isinstance(rule.get("course_id"), str):
            raise DegreeImportError(f"prerequisites/{index} requires course_id")
        all_of = rule.get("all_of", [])
        any_of = rule.get("any_of", [])
        minimum_semester = rule.get("minimum_semester")
        if not _string_list(all_of, allow_empty=True) or not isinstance(any_of, list):
            raise DegreeImportError(f"prerequisites/{index} has invalid AND/OR groups")
        if any(not _string_list(group) for group in any_of):
            raise DegreeImportError(f"prerequisites/{index} has an invalid OR group")
        if minimum_semester is not None and (
            isinstance(minimum_semester, bool)
            or not isinstance(minimum_semester, int)
            or not 1 <= minimum_semester <= 10
        ):
            raise DegreeImportError(f"prerequisites/{index} has invalid minimum_semester")
    return {
        "kind": "curriculum",
        "digest": source_digest(payload),
        "programme": programme,
        "courses": [asdict(course) for course in parsed],
        "relationships": relationships,
        "prerequisites": prerequisites,
        "warnings": warnings,
        "counts": {
            "courses": len(parsed),
            "relationships": len(relationships),
            "prerequisites": len(prerequisites),
        },
        "raw": payload,
    }


def parse_legacy_v6(
    payload: dict[str, Any], *, source_name: str, source_sequence: int
) -> dict[str, Any]:
    required = ("version", "catalog", "completed", "plan", "settings", "offerings")
    if payload.get("version") != 6 or any(key not in payload for key in required):
        raise DegreeImportError("legacy snapshot must be a version-6 document")
    if (
        not isinstance(payload["catalog"], list)
        or not isinstance(payload["completed"], list)
        or not isinstance(payload["plan"], dict)
    ):
        raise DegreeImportError("legacy catalog/completed/plan have invalid shapes")
    identities: dict[str, dict[str, Any]] = {}
    duplicate_looking: list[dict[str, Any]] = []
    appearance: dict[tuple[str, str], list[str]] = {}
    for index, row in enumerate(payload["catalog"]):
        if not isinstance(row, dict):
            raise DegreeImportError(f"catalog/{index} must be an object")
        identity = row.get("id") or row.get("courseId")
        if not isinstance(identity, str) or not identity:
            raise DegreeImportError(f"catalog/{index} has no stable id")
        if identity in identities:
            raise DegreeImportError(f"duplicate catalogue identity: {identity}")
        identities[identity] = row
        key = (
            str(row.get("code", "")).casefold(),
            str(row.get("title", row.get("name", ""))).casefold(),
        )
        appearance.setdefault(key, []).append(identity)
    for key, ids in appearance.items():
        if len(ids) > 1:
            duplicate_looking.append({"code": key[0], "title": key[1], "source_ids": ids})
    plan_rows: list[dict[str, Any]] = []
    for semester_key, rows in payload["plan"].items():
        if not isinstance(rows, list):
            raise DegreeImportError(f"plan/{semester_key} must be an array")
        semester = _semester_number(str(semester_key))
        for order, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("courseId"), str):
                raise DegreeImportError(f"plan/{semester_key}/{order} requires courseId")
            if row["courseId"] not in identities:
                raise DegreeImportError(f"plan references unknown courseId {row['courseId']}")
            plan_rows.append(
                {
                    "semester": semester,
                    "source_order": order,
                    "course_id": row["courseId"],
                    "raw": row,
                }
            )
    completed_refs = []
    warnings: list[dict[str, str]] = []
    for index, row in enumerate(payload["completed"]):
        if isinstance(row, str):
            identity = row
        elif isinstance(row, dict):
            identity = row.get("courseId") or row.get("id")
        else:
            identity = None
        if not isinstance(identity, str) or identity not in identities:
            warnings.append(
                {
                    "code": "unresolved_completed",
                    "message": f"completed/{index} could not be matched by source identity.",
                }
            )
        else:
            completed_refs.append(identity)
    return {
        "kind": "legacy_v6",
        "source_name": source_name,
        "source_sequence": source_sequence,
        "snapshot_id": source_digest(payload),
        "updated_at": payload.get("updatedAt"),
        "counts": {
            "catalog": len(identities),
            "completed": len(completed_refs),
            "planned": len(plan_rows),
        },
        "catalog": [
            {"source_id": identity, "source_order": index, "raw": row}
            for index, (identity, row) in enumerate(identities.items())
        ],
        "completed": completed_refs,
        "plan": plan_rows,
        "duplicate_looking": duplicate_looking,
        "warnings": warnings,
        "raw": payload,
    }


def diff_legacy(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    def locations(parsed: dict[str, Any]) -> dict[str, int]:
        return {str(row["course_id"]): int(row["semester"]) for row in parsed["plan"]}

    before = locations(first)
    after = locations(second)
    return {
        "from_snapshot": first["snapshot_id"],
        "to_snapshot": second["snapshot_id"],
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "moved": [
            {"course_id": key, "from_semester": before[key], "to_semester": after[key]}
            for key in sorted(before.keys() & after.keys())
            if before[key] != after[key]
        ],
        "completed_added": sorted(set(second["completed"]) - set(first["completed"])),
        "completed_removed": sorted(set(first["completed"]) - set(second["completed"])),
    }


def _semester_number(value: str) -> int:
    digits = "".join(character for character in value if character.isdigit())
    if not digits or not 1 <= int(digits) <= 10:
        raise DegreeImportError(f"unrecognized semester key: {value}")
    return int(digits)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DegreeImportError("L/T/P/J values must be non-negative integers")
    return value


def _string_list(value: object, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _evidence(value: object) -> EvidenceStatus:
    try:
        return EvidenceStatus(str(value))
    except ValueError as exc:
        raise DegreeImportError(f"unsupported provenance: {value}") from exc
