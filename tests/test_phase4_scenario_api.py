from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from test_phase3_solver_api import scenario_payload, seed, wait_for_job

from ffcs_studio.config import Settings
from ffcs_studio.web.app import create_app

BASE_URL = "http://127.0.0.1:8765"


def test_saved_scenario_result_restart_and_exports(tmp_path: Path) -> None:
    async def first_run() -> tuple[str, str]:
        app = create_app(Settings(data_dir=tmp_path, port=8765, solver_max_workers=1))
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                calendar_id, offerings = await seed(client, app.state.csrf_token)
                solver_payload = scenario_payload(calendar_id, offerings)
                created = await client.post(
                    "/api/v1/scenarios",
                    headers=headers,
                    json={
                        "name": "Restart-safe plan",
                        "description": "sanitized API fixture",
                        "document": {"schema_version": "1.0", **solver_payload},
                    },
                )
                assert created.status_code == 201, created.text
                scenario = created.json()
                assert scenario["current_revision"] == 1
                assert scenario["status"] == "ready"
                assert all(
                    item["source_revision_id"] is not None
                    for item in scenario["document"]["courses"]
                )

                stale = await client.put(
                    f"/api/v1/scenarios/{scenario['scenario_id']}",
                    headers=headers,
                    json={
                        "name": "stale",
                        "description": "",
                        "document": scenario["document"],
                        "expected_revision": 99,
                        "change_summary": "stale update",
                    },
                )
                assert stale.status_code == 409
                assert stale.json()["error"]["code"] == "scenario_revision_conflict"

                job_payload = {
                    key: value
                    for key, value in scenario["document"].items()
                    if key != "schema_version"
                }
                job = await client.post("/api/v1/solver/jobs", headers=headers, json=job_payload)
                assert job.status_code == 202, job.text
                job_id = job.json()["job_id"]
                status = await wait_for_job(client, job_id)
                assert status["status"] == "exhausted"
                result_page = (
                    await client.get(
                        f"/api/v1/solver/jobs/{job_id}/results",
                        params={"page": 1, "page_size": 2},
                    )
                ).json()
                saved_results = []
                for index, result_item in enumerate(result_page["items"], start=1):
                    saved = await client.post(
                        f"/api/v1/scenarios/{scenario['scenario_id']}/results",
                        headers=headers,
                        json={
                            "scenario_revision": 1,
                            "job_id": job_id,
                            "solver_result_id": result_item["result_id"],
                            "name": f"Timetable option {index}",
                        },
                    )
                    assert saved.status_code == 201, saved.text
                    saved_results.append(saved.json())
                saved_result = saved_results[0]
                assert saved_result["result"]["assignments"]
                assert saved_result["verification_status"] == "exploratory"

                listed = await client.get(f"/api/v1/scenarios/{scenario['scenario_id']}/results")
                assert listed.json()["total"] == 2
                preferred = await client.post(
                    f"/api/v1/saved-results/{saved_results[1]['saved_result_id']}/preferred",
                    headers=headers,
                    json={},
                )
                assert preferred.json()["is_preferred"] == 1

                unavailable_job = await client.post(
                    f"/api/v1/scenarios/{scenario['scenario_id']}/results",
                    headers=headers,
                    json={
                        "scenario_revision": 1,
                        "job_id": "missing-job",
                        "solver_result_id": result_page["items"][0]["result_id"],
                        "name": "Must not be fabricated",
                    },
                )
                assert unavailable_job.status_code == 404

                invalid = await client.post(
                    "/api/v1/scenarios",
                    headers=headers,
                    json={"name": "", "description": "", "document": {}},
                )
                assert invalid.status_code == 422

                draft = await client.post(
                    "/api/v1/scenarios",
                    headers=headers,
                    json={"name": "Incomplete draft", "description": "", "document": {}},
                )
                assert draft.status_code == 201
                assert draft.json()["status"] == "draft"
                return str(scenario["scenario_id"]), str(saved_result["saved_result_id"])
        finally:
            app.state.solver_jobs.shutdown()

    scenario_id, saved_result_id = asyncio.run(first_run())

    async def second_run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                scenario = await client.get(f"/api/v1/scenarios/{scenario_id}")
                assert scenario.status_code == 200
                assert scenario.json()["name"] == "Restart-safe plan"
                result = await client.get(f"/api/v1/saved-results/{saved_result_id}")
                assert result.status_code == 200
                assert result.json()["result"]["assignments"]
                listed = await client.get(f"/api/v1/scenarios/{scenario_id}/results")
                assert listed.json()["total"] == 2
                assert sum(item["is_preferred"] for item in listed.json()["items"]) == 1

                scenario_export = await client.get(f"/api/v1/scenarios/{scenario_id}/export")
                assert scenario_export.json()["kind"] == "ffcs-studio-scenario"
                json_export = await client.get(
                    f"/api/v1/saved-results/{saved_result_id}/export.json"
                )
                assert json_export.json()["kind"] == "ffcs-studio-timetable"
                csv_export = await client.get(f"/api/v1/saved-results/{saved_result_id}/export.csv")
                assert csv_export.text.startswith("\ufeffDay,Start,End,Course")
                assert "Preferred Faculty" in csv_export.text or "Other Faculty" in csv_export.text
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(second_run())


def test_scenario_writes_require_csrf(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                response = await client.post("/api/v1/scenarios", json={})
                assert response.status_code == 403
                assert response.json()["error"]["code"] == "invalid_csrf"
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())


def test_saved_result_csv_neutralizes_spreadsheet_formulas(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                calendar_id, offerings = await seed(client, app.state.csrf_token)
                document = {"schema_version": "1.0", **scenario_payload(calendar_id, offerings)}
                created = await client.post(
                    "/api/v1/scenarios",
                    headers=headers,
                    json={"name": "CSV safety", "description": "", "document": document},
                )
                assert created.status_code == 201
                scenario = created.json()
                stored = app.state.scenario_repository.save_result(
                    scenario_id=scenario["scenario_id"],
                    scenario_revision=1,
                    name="CSV injection fixture",
                    solver_result_id="fixture-result",
                    solver_fingerprint="fixture-fingerprint",
                    calendar_id=calendar_id,
                    result={
                        "assignments": [
                            {
                                "course_code": "=FORMULA()",
                                "meetings": [
                                    {
                                        "day_name": "Monday",
                                        "start_time": "09:00",
                                        "end_time": "09:50",
                                        "component_type": "TH",
                                        "faculty": "+DANGEROUS",
                                        "venue": "@CELL",
                                        "slot": "-1+1",
                                    }
                                ],
                            }
                        ]
                    },
                    source_references={"calendar_id": calendar_id, "offerings": []},
                    verification_status="exploratory",
                )
                exported = await client.get(
                    f"/api/v1/saved-results/{stored['saved_result_id']}/export.csv"
                )
                assert exported.status_code == 200
                assert "'=FORMULA()" in exported.text
                assert "'+DANGEROUS" in exported.text
                assert "'@CELL" in exported.text
                assert "'-1+1" in exported.text
        finally:
            app.state.solver_jobs.shutdown()

    asyncio.run(run())
