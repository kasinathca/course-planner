from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from ffcs_studio.config import Settings
from ffcs_studio.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8765"


def test_calendar_api_workflow_and_conflicts(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        headers = {"X-FFCS-CSRF": app.state.csrf_token}
        payload = json.loads(
            (ROOT / "examples" / "sample_slot_calendar_DRAFT.json").read_text(encoding="utf-8")
        )
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            empty = await client.get("/api/v1/calendars")
            assert empty.json()["items"] == []

            validated = await client.post(
                "/api/v1/calendars/validate", headers=headers, json=payload
            )
            assert validated.status_code == 200, validated.text
            assert validated.json()["calendar"]["verification_status"] == "draft_unverified"

            previewed = await client.post(
                "/api/v1/calendars/preview",
                headers=headers,
                json={"validation_id": validated.json()["validation_id"]},
            )
            assert previewed.json()["slot_count"] == 4
            committed = await client.post(
                "/api/v1/calendars/commit",
                headers=headers,
                json={"preview_id": previewed.json()["preview_id"]},
            )
            calendar_id = committed.json()["calendar_id"]
            assert committed.json()["active"] is True

            detail = await client.get(f"/api/v1/calendars/{calendar_id}")
            assert detail.json()["evidence"]["kind"] == "synthetic_example"

            resolved = await client.post(
                "/api/v1/slots/resolve",
                headers=headers,
                json={"calendar_id": calendar_id, "expression": "A1+L2"},
            )
            assert resolved.json()["resolved"] is True
            assert len(resolved.json()["intervals"]) == 3

            unknown = await client.post(
                "/api/v1/conflicts/check",
                headers=headers,
                json={"calendar_id": calendar_id, "left": "Z99", "right": "A2"},
            )
            assert unknown.json()["report"]["status"] == "unresolved"

            clash = await client.post(
                "/api/v1/conflicts/check",
                headers=headers,
                json={"calendar_id": calendar_id, "left": "A1", "right": "L1"},
            )
            assert clash.json()["report"]["status"] == "confirmed_clash"

    asyncio.run(run())


def test_calendar_writes_keep_csrf_protection(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            response = await client.post("/api/v1/calendars/validate", json={})
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "invalid_csrf"

    asyncio.run(run())
