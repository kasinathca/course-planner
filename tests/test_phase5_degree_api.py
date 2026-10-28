from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from ffcs_studio.config import Settings
from ffcs_studio.web.app import create_app
from ffcs_studio.web.routes.solver import ScenarioRequest, _scenario_input
from tests.test_phase3_solver_api import scenario_payload, seed
from tests.test_phase5_degree_persistence import plan_document, synthetic_curriculum

BASE_URL = "http://127.0.0.1:8765"


async def import_curriculum(client: httpx.AsyncClient, csrf: str) -> str:
    headers = {"X-FFCS-CSRF": csrf}
    validated = await client.post(
        "/api/v1/degree/imports/validate",
        headers=headers,
        json={
            "kind": "curriculum",
            "filename": "synthetic-public.json",
            "source_sequence": 1,
            "document": synthetic_curriculum(),
        },
    )
    assert validated.status_code == 200, validated.text
    preview = await client.post(
        "/api/v1/degree/imports/preview",
        headers=headers,
        json={"validation_id": validated.json()["validation_id"]},
    )
    assert preview.status_code == 200
    assert preview.json()["counts"]["courses"] == 5
    committed = await client.post(
        "/api/v1/degree/imports/commit",
        headers=headers,
        json={"preview_id": preview.json()["preview_id"]},
    )
    assert committed.status_code == 200
    return str(committed.json()["curriculum_id"])


def test_degree_api_import_plan_progress_revision_and_restart(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                assert (await client.get("/api/v1/programmes")).json()["items"]
                curriculum_id = await import_curriculum(client, app.state.csrf_token)
                catalog = await client.get(
                    "/api/v1/degree/catalog",
                    params={"curriculum_id": curriculum_id, "query": "SYN"},
                )
                assert catalog.status_code == 200
                assert catalog.json()["total"] == 5
                blank_document = {
                    "programme_code": "SYNTHETIC-IMTECH",
                    "curriculum_revision": "synthetic-v1",
                    "records": [],
                    "settings": {},
                    "semester_labels": {},
                }
                blank = await client.post(
                    "/api/v1/degree/plans",
                    headers=headers,
                    json={
                        "name": "Prerequisite recommendations",
                        "curriculum_id": curriculum_id,
                        "document": blank_document,
                    },
                )
                blocked = await client.get(
                    f"/api/v1/degree/plans/{blank.json()['degree_plan_id']}/recommendations",
                    params={"semester": 5},
                )
                blocked_codes = {item["course"]["course_code"] for item in blocked.json()["items"]}
                assert "SYN2001" not in blocked_codes
                assert "STS3022" in blocked_codes
                completed_document = {
                    **blank_document,
                    "records": [
                        {
                            "record_id": "completed-prerequisite",
                            "course_id": "syn-pc",
                            "semester": 4,
                            "status": "completed",
                            "intended_category": "PC",
                            "attempt": 1,
                            "notes": "",
                            "source": "manual",
                            "offering_id": None,
                        }
                    ],
                }
                await client.put(
                    f"/api/v1/degree/plans/{blank.json()['degree_plan_id']}",
                    headers=headers,
                    json={
                        "expected_revision": 1,
                        "name": "Prerequisite recommendations",
                        "change_summary": "Complete prerequisite",
                        "document": completed_document,
                    },
                )
                eligible = await client.get(
                    f"/api/v1/degree/plans/{blank.json()['degree_plan_id']}/recommendations",
                    params={"semester": 5},
                )
                eligible_elective = next(
                    item
                    for item in eligible.json()["items"]
                    if item["course"]["course_code"] == "SYN2001"
                )
                assert eligible_elective["prerequisite_status"]["status"] == "satisfied"
                created = await client.post(
                    "/api/v1/degree/plans",
                    headers=headers,
                    json={
                        "name": "Synthetic primary",
                        "curriculum_id": curriculum_id,
                        "document": plan_document(),
                    },
                )
                assert created.status_code == 201, created.text
                plan = created.json()
                plan_id = plan["degree_plan_id"]
                progress = await client.get(f"/api/v1/degree/plans/{plan_id}/progress")
                assert progress.status_code == 200, progress.text
                assert progress.json()["totals"]["earned_milli"] == 4000
                assert progress.json()["totals"]["planned_milli"] == 3500
                assert progress.json()["totals"]["graduation_status"] == ("not_officially_verified")

                moved = plan_document()
                moved["records"][1]["semester"] = 7  # type: ignore[index]
                preview_progress = await client.post(
                    "/api/v1/degree/progress/preview",
                    headers=headers,
                    json={"curriculum_id": curriculum_id, "document": moved},
                )
                assert preview_progress.status_code == 200, preview_progress.text
                assert preview_progress.json()["semesters"][5]["planned_milli"] == 0
                assert preview_progress.json()["semesters"][6]["planned_milli"] == 3500
                saved = await client.put(
                    f"/api/v1/degree/plans/{plan_id}",
                    headers=headers,
                    json={
                        "expected_revision": 1,
                        "name": "Synthetic primary",
                        "change_summary": "Move elective",
                        "document": moved,
                    },
                )
                assert saved.status_code == 200
                stale = await client.put(
                    f"/api/v1/degree/plans/{plan_id}",
                    headers=headers,
                    json={
                        "expected_revision": 1,
                        "name": "Stale writer",
                        "change_summary": "must fail",
                        "document": moved,
                    },
                )
                assert stale.status_code == 409
                compared = await client.get(
                    f"/api/v1/degree/plans/{plan_id}/compare",
                    params={"left_revision": 1, "right_revision": 2},
                )
                assert compared.json()["changed"][0]["after"]["semester"] == 7
                assert compared.json()["left_totals"] == compared.json()["right_totals"]
                assert compared.json()["category_changes"] == []
                recommendations = await client.get(
                    f"/api/v1/degree/plans/{plan_id}/recommendations",
                    params={"semester": 7},
                )
                assert recommendations.status_code == 200
                assert all("reason" in item for item in recommendations.json()["items"])
        finally:
            app.state.solver_jobs.shutdown()

        restarted = create_app(Settings(data_dir=tmp_path, port=8765))
        try:
            assert restarted.state.database_schema_version == 4
            stored = restarted.state.degree_repository.list_plans()
            assert stored[0]["current_revision"] == 2
        finally:
            restarted.state.solver_jobs.shutdown()

    asyncio.run(run())


def recovery_payload() -> dict[str, Any]:
    return {
        "intended": {"course-a": "a-1", "course-b": "b-1"},
        "options": {
            "course-a": [
                {
                    "option_id": "a-1",
                    "allocation_ids": [1],
                    "faculty": ["Synthetic Faculty A"],
                    "slot_keys": ["A1"],
                    "credits_milli": 3000,
                },
                {
                    "option_id": "a-2",
                    "allocation_ids": [2],
                    "faculty": ["Synthetic Faculty B"],
                    "slot_keys": ["B1"],
                    "credits_milli": 3000,
                },
            ],
            "course-b": [
                {
                    "option_id": "b-1",
                    "allocation_ids": [3],
                    "faculty": ["Synthetic Faculty C"],
                    "slot_keys": ["C1"],
                    "credits_milli": 3000,
                }
            ],
        },
        "registered_locks": {"course-b": "b-1"},
        "must_take": ["course-a", "course-b"],
        "blocked_allocations": [1],
        "priority": {},
        "source_revision_fingerprint": "synthetic-source-revision",
    }


def test_recovery_api_persists_proven_minimum_and_requires_csrf(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                rejected = await client.post("/api/v1/recovery/scenarios", json=recovery_payload())
                assert rejected.status_code == 403
                result = await client.post(
                    "/api/v1/recovery/scenarios",
                    headers={"X-FFCS-CSRF": app.state.csrf_token},
                    json=recovery_payload(),
                )
                assert result.status_code == 201, result.text
                assert result.json()["proven_minimum"] is True
                assert result.json()["minimum_score"][0] == 1
                assert result.json()["results"][0]["preserved_registrations"] == ["course-b"]
                with app.state.database.connection() as connection:
                    stored = connection.execute(
                        "SELECT status, proven_minimum FROM recovery_runs"
                    ).fetchone()
                assert tuple(stored) == ("exact", 1)
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())


def test_invalid_curriculum_and_request_shape_are_rejected(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                invalid = await client.post(
                    "/api/v1/degree/imports/validate",
                    headers=headers,
                    json={
                        "kind": "curriculum",
                        "filename": "invalid.json",
                        "document": {"schema_version": "1.0", "programme": {}, "courses": []},
                        "source_sequence": 1,
                    },
                )
                assert invalid.status_code == 400
                extra = await client.post(
                    "/api/v1/degree/plans",
                    headers=headers,
                    json={"name": "invalid", "curriculum_id": "none", "document": {}, "extra": 1},
                )
                assert extra.status_code == 422
                malformed_record = await client.post(
                    "/api/v1/degree/plans",
                    headers=headers,
                    json={
                        "name": "invalid",
                        "curriculum_id": "none",
                        "document": {
                            "programme_code": "SYN",
                            "curriculum_revision": "v1",
                            "records": [{"course_id": "missing-everything"}],
                        },
                    },
                )
                assert malformed_record.status_code == 422
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())


def test_legacy_snapshot_activation_uses_source_identity_and_keeps_timeline_distinct(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                curriculum_id = await import_curriculum(client, app.state.csrf_token)
                legacy = {
                    "version": 6,
                    "catalog": [
                        {"id": "legacy-pc", "code": "SYN1001", "title": "Synthetic Core"},
                        {
                            "id": "legacy-pe",
                            "code": "SYN2001",
                            "title": "Synthetic Elective",
                        },
                    ],
                    "completed": [{"courseId": "legacy-pc"}],
                    "plan": {"semester7": [{"courseId": "legacy-pe"}], "semester10": []},
                    "settings": {},
                    "offerings": {"historicalOnly": True},
                    "updatedAt": "2026-02-01T00:00:00Z",
                }
                validated = await client.post(
                    "/api/v1/degree/imports/validate",
                    headers=headers,
                    json={
                        "kind": "legacy_v6",
                        "filename": "synthetic-history.json",
                        "source_sequence": 2,
                        "document": legacy,
                    },
                )
                preview = await client.post(
                    "/api/v1/degree/imports/preview",
                    headers=headers,
                    json={"validation_id": validated.json()["validation_id"]},
                )
                committed = await client.post(
                    "/api/v1/degree/imports/commit",
                    headers=headers,
                    json={"preview_id": preview.json()["preview_id"]},
                )
                snapshot_id = committed.json()["snapshot_id"]
                activated = await client.post(
                    f"/api/v1/degree/imports/legacy/{snapshot_id}/activate",
                    headers=headers,
                    json={"curriculum_id": curriculum_id, "name": "Historical snapshot"},
                )
                assert activated.status_code == 201, activated.text
                records = activated.json()["document"]["records"]
                assert [(item["status"], item["semester"]) for item in records] == [
                    ("completed", 0),
                    ("planned", 7),
                ]
                assert activated.json()["source_snapshot_id"] == snapshot_id
                progress = await client.get(
                    f"/api/v1/degree/plans/{activated.json()['degree_plan_id']}/progress"
                )
                assert progress.json()["totals"]["earned_milli"] == 4000
                assert progress.json()["totals"]["planned_milli"] == 3500
        finally:
            app.state.recovery_jobs.shutdown()
            app.state.solver_jobs.shutdown()

    asyncio.run(run())


def test_saved_scenario_recovery_uses_solver_candidates_and_scoped_manual_states(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                calendar_id, offerings = await seed(client, app.state.csrf_token)
                document = {"schema_version": "1.0", **scenario_payload(calendar_id, offerings)}
                validation = app.state.solver_service.validate(
                    _scenario_input(ScenarioRequest.model_validate(document))
                )
                assert validation.valid and validation.scenario is not None
                courses = {course.course_code: course for course in validation.scenario.courses}
                required = courses["REQ1001"]
                optional = courses["OPT1001"]
                intended_required = required.candidates[0]
                replacement_required = required.candidates[1]
                intended_optional = optional.candidates[0]

                saved = await client.post(
                    "/api/v1/scenarios",
                    headers=headers,
                    json={"name": "Recovery source", "description": "", "document": document},
                )
                assert saved.status_code == 201, saved.text
                for candidate, state in (
                    (intended_required, "full"),
                    (intended_optional, "registered"),
                ):
                    allocation_id = candidate.allocation_ids[0]
                    recorded = await client.post(
                        "/api/v1/recovery/availability",
                        headers=headers,
                        json={
                            "campus": "Vellore",
                            "semester_label": "EXAMPLE_ONLY_NOT_OFFICIAL",
                            "offering_revision_id": candidate.revision_id,
                            "allocation_id": allocation_id,
                            "state": state,
                            "provenance": "manual",
                            "note": "Synthetic browser-independent acceptance state",
                            "captured_at": "2026-10-28T10:00:00+05:30",
                        },
                    )
                    assert recorded.status_code == 201, recorded.text
                recovered = await client.post(
                    f"/api/v1/recovery/scenarios/{saved.json()['scenario_id']}/run",
                    headers=headers,
                    json={
                        "expected_revision": 1,
                        "intended": {
                            str(required.offering_id): intended_required.candidate_id,
                            str(optional.offering_id): intended_optional.candidate_id,
                        },
                    },
                )
                assert recovered.status_code == 201, recovered.text
                result = recovered.json()
                assert result["proven_minimum"] is True
                assert result["minimum_score"][0] == 1
                selected = {
                    item["course_id"]: item["option_id"]
                    for item in result["results"][0]["selected"]
                }
                assert selected[str(required.offering_id)] == replacement_required.candidate_id
                assert result["results"][0]["preserved_registrations"] == [
                    str(optional.offering_id)
                ]

                latest = await client.post(
                    "/api/v1/recovery/availability",
                    headers=headers,
                    json={
                        "campus": "Vellore",
                        "semester_label": "EXAMPLE_ONLY_NOT_OFFICIAL",
                        "offering_revision_id": intended_required.revision_id,
                        "allocation_id": intended_required.allocation_ids[0],
                        "state": "available",
                        "provenance": "manual",
                        "note": "Synthetic state changed",
                        "captured_at": "2026-10-28T10:05:00+05:30",
                    },
                )
                current = await client.get(
                    "/api/v1/recovery/availability",
                    params={
                        "campus": "Vellore",
                        "semester_label": "EXAMPLE_ONLY_NOT_OFFICIAL",
                    },
                )
                matching = [
                    item
                    for item in current.json()["items"]
                    if item["allocation_id"] == intended_required.allocation_ids[0]
                ]
                assert len(matching) == 1
                assert matching[0]["availability_id"] == latest.json()["availability_id"]
                assert matching[0]["state"] == "available"
        finally:
            app.state.recovery_jobs.shutdown()
            app.state.solver_jobs.shutdown()

    asyncio.run(run())
