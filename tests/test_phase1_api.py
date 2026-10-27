from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from ffcs_studio.config import Settings
from ffcs_studio.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8765"


class ChunkedBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def test_security_and_complete_api_workflow(tmp_path: Path) -> None:
    async def run() -> None:
        settings = Settings(
            port=8765,
            data_dir=tmp_path / "isolated data",
            max_request_bytes=4096,
        )
        app = create_app(settings)
        token = app.state.csrf_token
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            landing = await client.get("/")
            assert landing.status_code == 200
            assert "Courses &amp; Data" in landing.text
            assert "Import courses" in landing.text
            assert str(tmp_path) not in landing.text

            invalid_host = await client.get("/health", headers={"Host": "attacker.example"})
            assert invalid_host.status_code == 400
            assert invalid_host.json()["error"]["code"] == "invalid_host"
            userinfo_host = await client.get(
                "/health", headers={"Host": "attacker.example@127.0.0.1:8765"}
            )
            assert userinfo_host.status_code == 400

            missing_csrf = await client.post(
                "/api/v1/imports/validate",
                headers={"Content-Type": "application/json", "X-FFCS-Filename": "x.json"},
                content=b"{}",
            )
            assert missing_csrf.status_code == 403
            assert missing_csrf.json()["error"]["code"] == "invalid_csrf"

            foreign_origin = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "X-FFCS-Filename": "x.json",
                    "X-FFCS-CSRF": token,
                    "Origin": "https://attacker.example",
                },
                content=b"{}",
            )
            assert foreign_origin.status_code == 403
            assert foreign_origin.json()["error"]["code"] == "invalid_origin"

            cross_site = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "X-FFCS-Filename": "x.json",
                    "X-FFCS-CSRF": token,
                    "Sec-Fetch-Site": "cross-site",
                },
                content=b"{}",
            )
            assert cross_site.status_code == 403

            unsafe_filename = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "X-FFCS-Filename": "../private.json",
                    "X-FFCS-CSRF": token,
                },
                content=b"{}",
            )
            assert unsafe_filename.status_code == 400
            assert unsafe_filename.json()["error"]["code"] == "unsafe_filename"
            assert str(tmp_path) not in unsafe_filename.text

            unsupported = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-FFCS-Filename": "capture.bin",
                    "X-FFCS-CSRF": token,
                },
                content=b"small",
            )
            assert unsupported.status_code == 415

            malformed_type = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "not/a-supported-type; broken",
                    "X-FFCS-Filename": "capture.txt",
                    "X-FFCS-CSRF": token,
                },
                content=b"small",
            )
            assert malformed_type.status_code == 415

            streamed = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "1",
                    "X-FFCS-Filename": "large.json",
                    "X-FFCS-CSRF": token,
                },
                content=ChunkedBody([b"x" * 2100, b"y" * 2100]),
            )
            assert streamed.status_code == 413
            assert streamed.json()["error"]["code"] == "request_too_large"

            declared = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "5000",
                    "X-FFCS-Filename": "large.json",
                    "X-FFCS-CSRF": token,
                },
                content=b"x",
            )
            assert declared.status_code == 413

            malformed_length = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "-1",
                    "X-FFCS-Filename": "capture.json",
                    "X-FFCS-CSRF": token,
                },
                content=b"{}",
            )
            assert malformed_length.status_code == 400
            assert malformed_length.json()["error"]["code"] == "invalid_content_length"

            fixture = (ROOT / "examples" / "vtop_selected_eth_ela.json").read_bytes()
            validate = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "application/json",
                    "X-FFCS-Filename": "crypto.json",
                    "X-FFCS-CSRF": token,
                    "Origin": BASE_URL,
                    "Sec-Fetch-Site": "same-origin",
                },
                content=fixture,
            )
            assert validate.status_code == 200, validate.text
            validated = validate.json()
            assert validated["course_count"] == 1
            assert validated["allocation_count"] == 12

            invalid_preview = await client.post(
                "/api/v1/imports/preview",
                headers={"X-FFCS-CSRF": token},
                json={"validation_id": "x" * 30},
            )
            assert invalid_preview.status_code == 410

            preview = await client.post(
                "/api/v1/imports/preview",
                headers={"X-FFCS-CSRF": token},
                json={"validation_id": validated["validation_id"]},
            )
            assert preview.status_code == 200
            previewed = preview.json()
            assert previewed["reconciliation"]["new_courses"] == 1
            assert previewed["reconciliation"]["added_rows"] == 12

            commit = await client.post(
                "/api/v1/imports/commit",
                headers={"X-FFCS-CSRF": token},
                json={"preview_id": previewed["preview_id"]},
            )
            assert commit.status_code == 200
            committed = commit.json()
            assert committed["status"] == "committed"

            semesters = await client.get("/api/v1/semesters")
            assert semesters.json()["items"] == [
                {
                    "campus": "Vellore",
                    "semester_label": "Winter Semester 2026-27",
                    "offering_count": 1,
                }
            ]
            offerings = await client.get(
                "/api/v1/offerings",
                params={
                    "campus": "Vellore",
                    "semester_label": "Winter Semester 2026-27",
                    "search": "cryptography",
                    "category": "PC",
                    "component": "ELA",
                },
            )
            payload = offerings.json()
            assert payload["total"] == 1
            assert payload["items"][0]["allocation_count"] == 12
            offering_id = payload["items"][0]["offering_id"]

            detail = await client.get(f"/api/v1/offerings/{offering_id}")
            allocations = await client.get(f"/api/v1/offerings/{offering_id}/allocations")
            assert detail.json()["source_kind"] == "vtop-tampermonkey"
            assert len(allocations.json()["items"]) == 12
            assert allocations.json()["items"][11]["slot"] == "L57+L58"

            imports = await client.get("/api/v1/imports")
            assert imports.json()["total"] == 1
            import_id = committed["import_id"]
            assert (await client.get(f"/api/v1/imports/{import_id}")).status_code == 200
            diff = await client.get(f"/api/v1/imports/{import_id}/diff")
            assert diff.json()["items"][0]["event_type"] == "new"

            empty = await client.get("/api/v1/offerings", params={"search": "absent"})
            assert empty.json()["items"] == []
            assert empty.json()["total"] == 0

        restarted = create_app(settings)
        restarted_transport = httpx.ASGITransport(app=restarted)
        async with httpx.AsyncClient(
            transport=restarted_transport, base_url=BASE_URL
        ) as restarted_client:
            persisted = await restarted_client.get("/api/v1/offerings")
            assert persisted.json()["total"] == 1
            assert persisted.json()["items"][0]["course_code"] == "CSI3002"

    asyncio.run(run())


def test_csv_api_requires_explicit_metadata(tmp_path: Path) -> None:
    async def run() -> None:
        app = create_app(Settings(data_dir=tmp_path, port=8765))
        transport = httpx.ASGITransport(app=app)
        csv_data = (
            b"semester_label,category,course_code,course_title,source_row,slot,venue,faculty,course_type\n"
            b'Winter 2026,PC,X1001,"Course, One",1,A1,SJT101,"DOE, JANE",TH\n'
        )
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            missing = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "text/csv",
                    "X-FFCS-Filename": "course.csv",
                    "X-FFCS-CSRF": app.state.csrf_token,
                },
                content=csv_data,
            )
            assert missing.status_code == 422
            assert missing.json()["error"]["issues"]

            valid = await client.post(
                "/api/v1/imports/validate",
                headers={
                    "Content-Type": "text/csv",
                    "X-FFCS-Filename": "course.csv",
                    "X-FFCS-CSRF": app.state.csrf_token,
                    "X-FFCS-Campus": "Vellore",
                    "X-FFCS-Semester": "Winter 2026",
                    "X-FFCS-Captured-At": "2026-10-28T09:00:00+05:30",
                },
                content=csv_data,
            )
            assert valid.status_code == 200, valid.text
            assert valid.json()["allocation_count"] == 1

    asyncio.run(run())
