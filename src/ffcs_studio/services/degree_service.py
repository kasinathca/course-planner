"""Application service for degree imports, progress, transfer and recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ffcs_studio.degree.accounting import evaluate_progress
from ffcs_studio.degree.importers import diff_legacy, parse_curriculum, parse_legacy_v6
from ffcs_studio.degree.models import (
    CatalogueCourse,
    CategoryRequirement,
    CourseRecord,
    CourseStatus,
    EvidenceStatus,
    PlanDocument,
    PrerequisiteRule,
    ProgrammePolicy,
    Relationship,
    RelationshipType,
)
from ffcs_studio.degree.prerequisites import evaluate_prerequisite
from ffcs_studio.degree.recovery import recover, request_from_payload
from ffcs_studio.persistence.degree_repository import DegreeRepository, DegreeRepositoryError
from ffcs_studio.persistence.scenario_repository import ScenarioRepository
from ffcs_studio.solver.models import CourseRole, ScenarioSnapshot


class DegreeServiceError(DegreeRepositoryError):
    code = "degree_service_error"


class DegreePreviewNotFound(DegreeServiceError):
    code = "degree_preview_not_found"


class DegreeService:
    def __init__(
        self, repository: DegreeRepository, scenario_repository: ScenarioRepository
    ) -> None:
        self.repository = repository
        self.scenario_repository = scenario_repository
        self._previews: dict[str, dict[str, Any]] = {}

    def validate_curriculum(self, payload: dict[str, Any], *, filename: str) -> dict[str, Any]:
        parsed = parse_curriculum(payload)
        token = self._store_preview({"kind": "curriculum", "filename": filename, "parsed": parsed})
        return {
            "validation_id": token,
            "valid": True,
            "digest": parsed["digest"],
            "counts": parsed["counts"],
            "warnings": parsed["warnings"],
        }

    def validate_legacy(
        self, payload: dict[str, Any], *, filename: str, source_sequence: int
    ) -> dict[str, Any]:
        parsed = parse_legacy_v6(payload, source_name=filename, source_sequence=source_sequence)
        token = self._store_preview({"kind": "legacy_v6", "filename": filename, "parsed": parsed})
        return {
            "validation_id": token,
            "valid": True,
            "snapshot_id": parsed["snapshot_id"],
            "counts": parsed["counts"],
            "warnings": parsed["warnings"],
            "duplicate_looking": parsed["duplicate_looking"],
        }

    def preview(self, validation_id: str) -> dict[str, Any]:
        stored = self._previews.get(validation_id)
        if stored is None:
            raise DegreePreviewNotFound("Degree import preview expired or was not found")
        parsed = stored["parsed"]
        preview_id = self._store_preview({**stored, "validated_id": validation_id})
        public = {key: value for key, value in parsed.items() if key not in {"raw", "catalog"}}
        if stored["kind"] == "legacy_v6":
            public["catalog_preview"] = parsed["catalog"][:25]
            public["plan"] = parsed["plan"]
        else:
            public["courses"] = parsed["courses"][:100]
        return {
            "preview_id": preview_id,
            "kind": stored["kind"],
            "filename": stored["filename"],
            **public,
        }

    def commit(self, preview_id: str) -> dict[str, Any]:
        stored = self._previews.pop(preview_id, None)
        if stored is None:
            raise DegreePreviewNotFound("Degree import preview expired or was not found")
        if stored["kind"] == "curriculum":
            return self.repository.commit_curriculum(stored["parsed"], filename=stored["filename"])
        return self.repository.commit_legacy(stored["parsed"])

    def compare_legacy(self, left_snapshot_id: str, right_snapshot_id: str) -> dict[str, Any]:
        imports = self.repository.list_legacy_imports()
        lookup = {item["snapshot_id"]: item["preview"] for item in imports}
        if left_snapshot_id not in lookup or right_snapshot_id not in lookup:
            raise DegreeServiceError("Both legacy snapshots must be committed before comparison")
        return diff_legacy(lookup[left_snapshot_id], lookup[right_snapshot_id])

    def activate_legacy_snapshot(
        self, *, snapshot_id: str, curriculum_id: str, name: str
    ) -> dict[str, Any]:
        snapshot = self.repository.legacy_snapshot(snapshot_id)["preview"]
        curriculum = self.repository.get_curriculum(curriculum_id)
        catalogue = self.repository.list_catalogue(curriculum_id, page_size=1000)["items"]
        by_source = {
            str(item["source_identity"]): str(item["catalogue_course_id"]) for item in catalogue
        }
        referenced = {
            *snapshot.get("completed", []),
            *(str(item["course_id"]) for item in snapshot.get("plan", [])),
        }
        unresolved = sorted(str(identity) for identity in referenced if identity not in by_source)
        if unresolved:
            raise DegreeServiceError(
                "Legacy activation requires reviewed source-identity mappings for: "
                + ", ".join(unresolved[:20])
            )
        records: list[dict[str, Any]] = []
        for order, source_id in enumerate(snapshot.get("completed", [])):
            records.append(
                {
                    "record_id": f"legacy-completed-{order}-{uuid4().hex[:8]}",
                    "course_id": by_source[source_id],
                    "semester": 0,
                    "status": "completed",
                    "intended_category": None,
                    "notes": "Completion semester was not present in the legacy snapshot.",
                    "source": "legacy",
                    "attempt": 1,
                    "offering_id": None,
                }
            )
        for item in snapshot.get("plan", []):
            records.append(
                {
                    "record_id": (f"legacy-plan-{item['source_order']}-{uuid4().hex[:8]}"),
                    "course_id": by_source[str(item["course_id"])],
                    "semester": int(item["semester"]),
                    "status": "planned",
                    "intended_category": None,
                    "notes": "Imported as historical planned status; not promoted to completion.",
                    "source": "legacy",
                    "attempt": 1,
                    "offering_id": None,
                }
            )
        document = {
            "programme_code": curriculum["programme_code"],
            "curriculum_revision": curriculum["revision_code"],
            "records": records,
            "settings": {"legacy_snapshot_id": snapshot_id},
            "semester_labels": {},
        }
        return self.repository.create_plan(
            name=name,
            curriculum_id=curriculum_id,
            document=document,
            source_snapshot_id=snapshot_id,
        )

    def progress(self, plan_id: str, *, revision: int | None = None) -> dict[str, Any]:
        stored = self.repository.get_plan(plan_id, revision=revision)
        result = self.progress_document(str(stored["curriculum_id"]), stored["document"])
        return {
            "degree_plan_id": plan_id,
            "revision": stored["revision"],
            **result,
        }

    def progress_document(
        self, curriculum_id: str, document_value: dict[str, Any]
    ) -> dict[str, Any]:
        curriculum = self.repository.get_curriculum(curriculum_id)
        catalogue_rows = self.repository.list_catalogue(curriculum_id, page_size=1000)["items"]
        policy = _policy(curriculum)
        courses = {row["catalogue_course_id"]: _course(row) for row in catalogue_rows}
        normalized = self.repository.normalize_plan_document(curriculum_id, document_value)
        document = _document(normalized)
        relationships = self._relationships(curriculum_id)
        return evaluate_progress(policy, courses, document, relationships)

    def compare_plans(
        self, plan_id: str, left_revision: int, right_revision: int
    ) -> dict[str, Any]:
        changes = self.repository.compare_plans(plan_id, left_revision, right_revision)
        left = self.progress(plan_id, revision=left_revision)
        right = self.progress(plan_id, revision=right_revision)
        left_categories = {row["code"]: row for row in left["categories"]}
        right_categories = {row["code"]: row for row in right["categories"]}
        category_changes = []
        for code in sorted(left_categories.keys() | right_categories.keys()):
            before = left_categories.get(code, {})
            after = right_categories.get(code, {})
            if before != after:
                category_changes.append({"code": code, "before": before, "after": after})
        return {
            **changes,
            "left_totals": left["totals"],
            "right_totals": right["totals"],
            "category_changes": category_changes,
        }

    def recommendations(
        self, plan_id: str, *, semester: int, offered_only: bool = False
    ) -> dict[str, Any]:
        stored = self.repository.get_plan(plan_id)
        progress = self.progress(plan_id)
        planned_ids = {
            row["course_id"]
            for row in stored["document"].get("records", [])
            if row["status"] not in {"withdrawn", "failed"}
        }
        completed_ids = {
            row["course_id"]
            for row in stored["document"].get("records", [])
            if row["status"] == "completed"
        }
        relationships = self._relationships(str(stored["curriculum_id"]))
        equivalent_completed = set(completed_ids)
        for relationship in relationships:
            if (
                relationship.verified
                and relationship.relationship_type == RelationshipType.EQUIVALENT
                and completed_ids.intersection(relationship.course_ids)
            ):
                equivalent_completed.update(relationship.course_ids)
        prerequisite_rules = self._prerequisites(str(stored["curriculum_id"]))
        waivers = {
            str(item)
            for item in stored["document"].get("settings", {}).get("prerequisite_waivers", [])
        }
        needed = {
            row["code"]: row["projected_remaining_milli"]
            for row in progress["categories"]
            if row["projected_remaining_milli"] not in (None, 0)
        }
        items = []
        for course in self.repository.list_catalogue(str(stored["curriculum_id"]), page_size=1000)[
            "items"
        ]:
            if (
                course["catalogue_course_id"] in planned_ids
                or course["category_code"] not in needed
            ):
                continue
            eligibility = evaluate_prerequisite(
                str(course["catalogue_course_id"]),
                completed_ids,
                semester,
                prerequisite_rules,
                waivers=waivers,
                equivalent_completed=equivalent_completed,
            )
            if eligibility["status"] == "blocked":
                continue
            offering = self._matching_offering(
                course["course_code"],
                stored["document"].get("semester_labels", {}).get(str(semester)),
            )
            if offered_only and offering is None:
                continue
            items.append(
                {
                    "course": course,
                    "offering": offering,
                    "scheduleable": offering is not None,
                    "reason": (
                        f"{course['category_code']} still has confirmed remaining requirements."
                    ),
                    "missing_evidence": (["current-semester offering"] if offering is None else [])
                    + (
                        ["prerequisites not verified"]
                        if eligibility["status"] == "not_verified"
                        else []
                    ),
                    "prerequisite_status": eligibility,
                }
            )
        items.sort(
            key=lambda item: (
                not item["scheduleable"],
                item["course"]["category_code"],
                item["course"]["course_code"],
                item["course"]["source_order"],
            )
        )
        return {"items": items[:100], "semester": semester, "deterministic": True}

    def transfer_preview(
        self,
        plan_id: str,
        *,
        semester: int,
        campus: str,
        semester_label: str,
        calendar_id: str,
        roles: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        plan = self.repository.get_plan(plan_id)
        catalogue = {
            row["catalogue_course_id"]: row
            for row in self.repository.list_catalogue(str(plan["curriculum_id"]), page_size=1000)[
                "items"
            ]
        }
        selected = [
            row
            for row in plan["document"].get("records", [])
            if int(row["semester"]) == semester
            and row["status"] in {"planned", "tentative", "enrolled"}
        ]
        mappings = []
        issues = []
        scenario_courses = []
        for row in selected:
            course = catalogue.get(row["course_id"])
            if course is None:
                issues.append({"course_id": row["course_id"], "code": "catalogue_missing"})
                continue
            offering = self._matching_offering(course["course_code"], semester_label, campus)
            if offering is None:
                issues.append(
                    {
                        "course_id": row["course_id"],
                        "course_code": course["course_code"],
                        "code": "offering_unknown",
                    }
                )
                continue
            role = (roles or {}).get(row["course_id"], "required")
            scenario_courses.append(
                {
                    "offering_id": offering["offering_id"],
                    "role": role,
                    "curriculum_type": course["curriculum_type"],
                    "curriculum_source": course["provenance"],
                    "credits": None
                    if course["total_credits_milli"] is None
                    else str(course["total_credits_milli"] / 1000),
                    "credit_source": course["provenance"],
                    "priority_tier": 1,
                }
            )
            mappings.append(
                {
                    "catalogue_course_id": row["course_id"],
                    "offering_id": offering["offering_id"],
                    "revision_id": offering["active_revision_id"],
                    "course_code": course["course_code"],
                }
            )
        document = {
            "schema_version": "1.0",
            "campus": campus,
            "semester_label": semester_label,
            "calendar_id": calendar_id,
            "mode": "exploratory",
            "courses": scenario_courses,
            "occupied_intervals": [],
            "credit_constraints": {},
            "ranking": {},
            "provisional_policy": {
                "allow_unverified_calendar": True,
                "allow_user_supplied_metadata": True,
            },
            "top_k": 20,
            "max_search_nodes": 2_000_000,
            "degree_context": {
                "degree_plan_id": plan_id,
                "degree_plan_revision": plan["revision"],
                "semester": semester,
                "curriculum_id": plan["curriculum_id"],
                "mappings": mappings,
            },
        }
        return {
            "ready": bool(selected) and not issues,
            "issues": issues,
            "mappings": mappings,
            "document": document,
        }

    def transfer_commit(
        self, plan_id: str, *, name: str, preview: dict[str, Any]
    ) -> dict[str, Any]:
        if not preview.get("ready"):
            raise DegreeServiceError("Semester transfer has unresolved offering mappings")
        document = preview["document"]
        stored = self.scenario_repository.create(
            name=name,
            description=(
                f"Transferred from degree plan {plan_id}, semester "
                f"{document['degree_context']['semester']}"
            ),
            document=document,
            source_references={
                "calendar_id": document["calendar_id"],
                "offerings": preview["mappings"],
                "degree_context": document["degree_context"],
            },
            status="draft",
            change_summary="Created from reviewed degree-plan transfer",
        )
        return stored

    def recovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = recover(request_from_payload(payload))
        return self.repository.save_recovery(
            request=payload,
            result=result,
            scenario_id=payload.get("scenario_id"),
            scenario_revision=payload.get("scenario_revision"),
            fingerprint=str(payload.get("source_revision_fingerprint", "manual-preview")),
        )

    def recovery_from_snapshot(
        self,
        *,
        stored_scenario: dict[str, Any],
        snapshot: ScenarioSnapshot,
        intended: dict[str, str],
        unlock_courses: set[str],
        max_nodes: int,
        top_k: int,
    ) -> dict[str, Any]:
        availability = self.repository.list_availability(
            campus=snapshot.campus,
            semester_label=snapshot.semester_label,
        )
        current: dict[tuple[int, int], dict[str, Any]] = {}
        for item in availability:
            key = (int(item["offering_revision_id"]), int(item["allocation_id"]))
            current.setdefault(key, item)
        blocked_states = {"full", "unavailable", "registration_failed"}
        blocked_allocations = {
            allocation_id
            for (revision_id, allocation_id), item in current.items()
            if item["state"] in blocked_states
            and any(course.revision_id == revision_id for course in snapshot.courses)
        }
        options: dict[str, list[dict[str, Any]]] = {}
        registered_locks: dict[str, str] = {}
        must_take: list[str] = []
        priority: dict[str, int] = {}
        normalized_intended: dict[str, str] = {}
        for course in snapshot.courses:
            if course.role is CourseRole.EXCLUDED:
                continue
            course_key = str(course.offering_id)
            if course.role is CourseRole.REQUIRED:
                must_take.append(course_key)
            priority[course_key] = course.priority_tier
            options[course_key] = [
                {
                    "option_id": candidate.candidate_id,
                    "allocation_ids": list(candidate.allocation_ids),
                    "faculty": sorted({meeting.faculty for meeting in candidate.meetings}),
                    "slot_keys": sorted({meeting.slot for meeting in candidate.meetings}),
                    "lab_sessions": sum(meeting.kind == "lab" for meeting in candidate.meetings),
                    "credits_milli": course.credit_milli or 0,
                    "meetings": [
                        {
                            "day": meeting.day,
                            "start_minute": meeting.start_minute,
                            "end_minute": meeting.end_minute,
                        }
                        for meeting in candidate.meetings
                    ],
                    "evidence_status": candidate.verification_status,
                    "assumptions": list(candidate.assumptions),
                }
                for candidate in course.candidates
            ]
            chosen = intended.get(course_key) or intended.get(course.course_code)
            if chosen is None and len(course.candidates) == 1:
                chosen = course.candidates[0].candidate_id
            if chosen is None:
                raise DegreeServiceError(
                    f"An intended exact option is required for {course.course_code}"
                )
            normalized_intended[course_key] = chosen
            unlock = course_key in unlock_courses or course.course_code in unlock_courses
            registered = {
                allocation_id
                for (revision_id, allocation_id), item in current.items()
                if revision_id == course.revision_id and item["state"] == "registered"
            }
            if registered and not unlock:
                matching = [
                    candidate.candidate_id
                    for candidate in course.candidates
                    if registered <= set(candidate.allocation_ids)
                ]
                registered_locks[course_key] = (
                    matching[0] if len(matching) == 1 else "registered-selection-missing"
                )
        payload = {
            "intended": normalized_intended,
            "options": options,
            "registered_locks": registered_locks,
            "must_take": must_take,
            "blocked_allocations": sorted(blocked_allocations),
            "priority": priority,
            "scenario_id": stored_scenario["scenario_id"],
            "scenario_revision": stored_scenario["revision"],
            "source_revision_fingerprint": snapshot.fingerprint,
            "max_nodes": max_nodes,
            "top_k": top_k,
        }
        return self.recovery(payload)

    def _store_preview(self, value: dict[str, Any]) -> str:
        token = uuid4().hex
        value["created_at"] = datetime.now(UTC).isoformat()
        self._previews[token] = value
        while len(self._previews) > 50:
            self._previews.pop(next(iter(self._previews)))
        return token

    def _relationships(self, curriculum_id: str) -> tuple[Relationship, ...]:
        with self.repository.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM course_relationships WHERE curriculum_id = ?", (curriculum_id,)
            ).fetchall()
        return tuple(
            Relationship(
                relationship_id=str(row["relationship_id"]),
                relationship_type=RelationshipType(str(row["relationship_type"])),
                course_ids=tuple(json.loads(row["course_ids_json"])),
                requirement_key=row["requirement_key"],
                verified=bool(row["verified"]),
                provenance=EvidenceStatus(str(row["provenance"])),
                notes=str(row["notes"]),
            )
            for row in rows
        )

    def _matching_offering(
        self, code: str, semester_label: str | None, campus: str = "Vellore"
    ) -> dict[str, Any] | None:
        if not semester_label:
            return None
        with self.repository.database.connection() as connection:
            row = connection.execute(
                "SELECT offering_id, active_revision_id, campus, semester_label, course_code "
                "FROM offerings WHERE campus = ? AND semester_label = ? AND course_code = ?",
                (campus, semester_label, code),
            ).fetchone()
        return dict(row) if row is not None else None

    def _prerequisites(self, curriculum_id: str) -> tuple[PrerequisiteRule, ...]:
        with self.repository.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM prerequisite_rules WHERE curriculum_id = ?",
                (curriculum_id,),
            ).fetchall()
        return tuple(
            PrerequisiteRule(
                rule_id=str(row["prerequisite_rule_id"]),
                course_id=str(row["catalogue_course_id"]),
                all_of=tuple(json.loads(row["all_of_json"])),
                any_of=tuple(tuple(group) for group in json.loads(row["any_of_json"])),
                minimum_semester=row["minimum_semester"],
                verified=bool(row["verified"]),
                provenance=EvidenceStatus(str(row["provenance"])),
            )
            for row in rows
        )


def _policy(row: dict[str, Any]) -> ProgrammePolicy:
    return ProgrammePolicy(
        programme_code=str(row["programme_code"]),
        name=str(row["programme_name"]),
        admission_batch=str(row["admission_batch"]),
        revision_code=str(row["revision_code"]),
        displayed_total_milli=int(row["displayed_total_milli"]),
        categories=tuple(
            CategoryRequirement(
                code=str(item["category_code"]),
                name=str(item["category_name"]),
                recorded_target_milli=int(item["recorded_target_milli"]),
                confirmed_credit_target_milli=item["confirmed_credit_target_milli"],
                non_credit_target_units=int(item["non_credit_target_units"]),
                counted_in_graduation=None
                if item["counted_in_graduation"] is None
                else bool(item["counted_in_graduation"]),
                surplus_allowed=bool(item["surplus_allowed"]),
                notes=str(item["notes"]),
            )
            for item in row["categories"]
        ),
        planning_warning_milli=27_000,
    )


def _course(row: dict[str, Any]) -> CatalogueCourse:
    return CatalogueCourse(
        canonical_id=str(row["catalogue_course_id"]),
        source_id=str(row["source_identity"]),
        code=str(row["course_code"]),
        title=str(row["course_title"]),
        category=str(row["category_code"]),
        curriculum_type=str(row["curriculum_type"]),
        total_credits_milli=row["total_credits_milli"],
        lecture=row["lecture"],
        tutorial=row["tutorial"],
        practical=row["practical"],
        project=row["project"],
        provenance=EvidenceStatus(str(row["provenance"])),
        alternative_group=row["alternative_group"],
        notes=str(row["notes"]),
        unresolved=tuple(row["unresolved"]),
    )


def _document(value: dict[str, Any]) -> PlanDocument:
    return PlanDocument(
        programme_code=str(value["programme_code"]),
        curriculum_revision=str(value["curriculum_revision"]),
        records=tuple(
            CourseRecord(
                record_id=str(row["record_id"]),
                course_id=str(row["course_id"]),
                semester=int(row["semester"]),
                status=CourseStatus(str(row["status"])),
                intended_category=row.get("intended_category"),
                notes=str(row.get("notes", "")),
                source=EvidenceStatus(str(row.get("source", "manual"))),
                attempt=int(row.get("attempt", 1)),
                offering_id=row.get("offering_id"),
            )
            for row in value.get("records", [])
        ),
        settings=dict(value.get("settings", {})),
    )
