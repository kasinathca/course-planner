from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from ffcs_studio.config import Settings
from ffcs_studio.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8765"


def source_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "source": "vtop-tampermonkey",
        "campus": "Vellore",
        "semester_label": "EXAMPLE_ONLY_NOT_OFFICIAL",
        "captured_at": "2026-10-28T00:00:00+05:30",
        "courses": [
            {
                "category": "PC",
                "course_code": "REQ1001",
                "course_title": "Required Course",
                "allocations": [
                    {
                        "source_row": 1,
                        "slot": "A1",
                        "venue": "R1",
                        "faculty": "Preferred Faculty",
                        "course_type": "TH",
                    },
                    {
                        "source_row": 2,
                        "slot": "A2",
                        "venue": "R2",
                        "faculty": "Other Faculty",
                        "course_type": "TH",
                    },
                ],
            },
            {
                "category": "PE",
                "course_code": "OPT1001",
                "course_title": "Optional Course",
                "allocations": [
                    {
                        "source_row": 1,
                        "slot": "L1",
                        "venue": "LAB",
                        "faculty": "Lab Faculty",
                        "course_type": "ELA",
                    }
                ],
            },
        ],
    }


async def seed(client: httpx.AsyncClient, csrf: str) -> tuple[str, dict[str, int]]:
    headers = {"X-FFCS-CSRF": csrf}
    payload = json.dumps(source_payload()).encode()
    validated = await client.post(
        "/api/v1/imports/validate",
        headers={
            **headers,
            "Content-Type": "application/json",
            "X-FFCS-Filename": "phase3-public-test.json",
        },
        content=payload,
    )
    preview = await client.post(
        "/api/v1/imports/preview",
        headers=headers,
        json={"validation_id": validated.json()["validation_id"]},
    )
    committed = await client.post(
        "/api/v1/imports/commit",
        headers=headers,
        json={"preview_id": preview.json()["preview_id"]},
    )
    assert committed.status_code == 200
    calendar_payload = json.loads(
        (ROOT / "examples" / "sample_slot_calendar_DRAFT.json").read_text(encoding="utf-8")
    )
    calendar_validated = await client.post(
        "/api/v1/calendars/validate", headers=headers, json=calendar_payload
    )
    calendar_preview = await client.post(
        "/api/v1/calendars/preview",
        headers=headers,
        json={"validation_id": calendar_validated.json()["validation_id"]},
    )
    calendar_commit = await client.post(
        "/api/v1/calendars/commit",
        headers=headers,
        json={"preview_id": calendar_preview.json()["preview_id"]},
    )
    offerings = (await client.get("/api/v1/offerings", params={"page_size": 100})).json()["items"]
    return calendar_commit.json()["calendar_id"], {
        item["course_code"]: item["offering_id"] for item in offerings
    }


def scenario_payload(calendar_id: str, offerings: dict[str, int]) -> dict[str, Any]:
    return {
        "campus": "Vellore",
        "semester_label": "EXAMPLE_ONLY_NOT_OFFICIAL",
        "calendar_id": calendar_id,
        "mode": "exploratory",
        "courses": [
            {
                "offering_id": offerings["REQ1001"],
                "role": "required",
                "curriculum_type": "TH",
                "curriculum_source": "user_supplied",
                "credits": "3",
                "credit_source": "user_supplied",
                "priority_tier": 1,
            },
            {
                "offering_id": offerings["OPT1001"],
                "role": "optional",
                "curriculum_type": "LO",
                "curriculum_source": "user_supplied",
                "credits": "1",
                "credit_source": "user_supplied",
                "priority_tier": 1,
            },
        ],
        "credit_constraints": {"minimum": "3", "target": "4", "maximum": "4"},
        "ranking": {"preferred_faculties": ["Preferred Faculty"]},
        "provisional_policy": {
            "allow_unverified_calendar": True,
            "allow_user_supplied_metadata": True,
        },
        "top_k": 10,
        "max_search_nodes": 100000,
    }


async def wait_for_job(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    for _attempt in range(200):
        status = (await client.get(f"/api/v1/solver/jobs/{job_id}")).json()
        if status["status"] not in {"queued", "running", "cancellation_requested"}:
            return status
        await asyncio.sleep(0.025)
    raise AssertionError("solver job did not finish")


async def wait_for_count(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    for _attempt in range(200):
        status = (await client.get(f"/api/v1/solver/jobs/{job_id}/count")).json()
        if status["status"] not in {"pending", "running"}:
            return status
        await asyncio.sleep(0.025)
    raise AssertionError("count job did not finish")


def test_solver_api_full_flow_and_exact_count(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(
            Settings(
                data_dir=tmp_path,
                port=8765,
                solver_max_workers=1,
                solver_cancel_grace_seconds=0.2,
            )
        )
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                calendar_id, offerings = await seed(client, app.state.csrf_token)
                payload = scenario_payload(calendar_id, offerings)
                validation = await client.post(
                    "/api/v1/solver/scenarios/validate", headers=headers, json=payload
                )
                assert validation.status_code == 200, validation.text
                assert validation.json()["valid"] is True
                assert validation.json()["candidate_count"] == 3
                assert validation.json()["assumptions"]

                created = await client.post("/api/v1/solver/jobs", headers=headers, json=payload)
                assert created.status_code == 202, created.text
                job_id = created.json()["job_id"]
                status = await wait_for_job(client, job_id)
                assert status["status"] == "exhausted"
                assert status["exhaustive"] is True

                results = await client.get(
                    f"/api/v1/solver/jobs/{job_id}/results",
                    params={"page": 1, "page_size": 10},
                )
                result_payload = results.json()
                assert result_payload["total"] == 3
                assert result_payload["items"][0]["verification_status"] == "exploratory"
                assert result_payload["items"][0]["selected_courses"] == [
                    "OPT1001",
                    "REQ1001",
                ]
                assert result_payload["items"][0]["course_metadata"][0]["credit_source"] == (
                    "user_supplied"
                )
                assert result_payload["items"][0]["metrics"]["daily_spans"]
                allocation_ids = {
                    allocation_id
                    for assignment in result_payload["items"][0]["assignments"]
                    for allocation_id in assignment["allocation_ids"]
                }
                assert allocation_ids

                count_started = await client.post(
                    f"/api/v1/solver/jobs/{job_id}/count", headers=headers
                )
                assert count_started.status_code == 202
                counted = await wait_for_count(client, job_id)
                assert counted["status"] == "exact"
                assert counted["result"]["exact_count"] == 3

                faculty_locked = scenario_payload(calendar_id, offerings)
                faculty_locked["courses"][0]["locked_faculties"] = ["Preferred Faculty"]
                locked_validation = await client.post(
                    "/api/v1/solver/scenarios/validate",
                    headers=headers,
                    json=faculty_locked,
                )
                assert locked_validation.json()["valid"] is True
                assert locked_validation.json()["candidate_count"] == 2

                faculty_locked["courses"][0]["forbidden_faculties"] = ["Preferred Faculty"]
                contradictory = await client.post(
                    "/api/v1/solver/scenarios/validate",
                    headers=headers,
                    json=faculty_locked,
                )
                assert contradictory.json()["valid"] is False
                assert {item["code"] for item in contradictory.json()["issues"]} == {
                    "no_complete_registration_option"
                }
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())


def test_strict_and_semester_mismatch_are_blocked(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                calendar_id, offerings = await seed(client, app.state.csrf_token)
                strict = scenario_payload(calendar_id, offerings)
                strict["mode"] = "strict_verified"
                response = await client.post(
                    "/api/v1/solver/scenarios/validate", headers=headers, json=strict
                )
                codes = {item["code"] for item in response.json()["issues"]}
                assert "calendar_not_officially_verified" in codes
                assert "curriculum_metadata_not_verified" in codes
                assert "credit_metadata_not_verified" in codes

                mismatch = scenario_payload(calendar_id, offerings)
                mismatch["semester_label"] = "Winter Semester 2026-27"
                created = await client.post("/api/v1/solver/jobs", headers=headers, json=mismatch)
                assert created.status_code == 422
                mismatch_codes = {item["code"] for item in created.json()["issues"]}
                assert "calendar_semester_mismatch" in mismatch_codes
                assert "offering_semester_mismatch" in mismatch_codes
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())


def test_solver_writes_require_csrf(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                response = await client.post("/api/v1/solver/jobs", json={})
                assert response.status_code == 403
                assert response.json()["error"]["code"] == "invalid_csrf"
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())
