from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from ffcs_studio.config import ConfigurationError, Settings
from ffcs_studio.web.app import create_app


def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        with TemporaryDirectory() as directory:
            settings = Settings(port=8765, data_dir=Path(directory))
            transport = httpx.ASGITransport(app=create_app(settings))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8765",
            ) as client:
                return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_health_endpoint_is_ready_and_private() -> None:
    response = request("GET", "/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "application": "ffcs-studio",
        "version": "0.6.0",
        "schema_version": "1.0.0",
    }
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_landing_page_and_local_static_assets() -> None:
    response = request("GET", "/")
    assert response.status_code == 200
    assert "Local planning workspace" in response.text
    assert "Timetable Planner" in response.text
    assert "Scenarios" in response.text
    assert "Build a clash-free week" in response.text
    assert "https://" not in response.text
    assert "http://" not in response.text
    assert request("GET", "/static/css/app.css").status_code == 200
    assert request("GET", "/static/css/timetable.css").status_code == 200
    assert request("GET", "/static/js/app.js").status_code == 200
    assert request("GET", "/static/js/modules/scenarios.js").status_code == 200


def test_solver_routes_are_in_the_local_openapi_contract() -> None:
    paths = request("GET", "/api/openapi.json").json()["paths"]
    assert "/api/v1/solver/scenarios/validate" in paths
    assert "/api/v1/solver/jobs" in paths
    assert "/api/v1/solver/jobs/{job_id}/count" in paths
    assert "/api/v1/scenarios" in paths
    assert "/api/v1/scenarios/{scenario_id}/revisions" in paths
    assert "/api/v1/saved-results/{saved_result_id}" in paths


def test_openapi_contract_is_local_without_cdn_documentation() -> None:
    contract = request("GET", "/api/openapi.json")
    assert contract.status_code == 200
    assert contract.json()["info"]["title"] == "FFCS Studio"
    assert request("GET", "/api/docs").status_code == 404


def test_unknown_path_has_predictable_json_error() -> None:
    response = request("GET", "/missing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_untrusted_host_is_rejected() -> None:
    response = request("GET", "/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_host"


def test_cross_origin_write_and_oversize_body_are_rejected() -> None:
    cross_origin = request(
        "POST",
        "/missing",
        headers={"Origin": "https://attacker.example"},
    )
    assert cross_origin.status_code == 403
    assert cross_origin.json()["error"]["code"] == "invalid_origin"

    oversized = request(
        "POST",
        "/missing",
        content=b"x",
        headers={"Content-Length": "1048577"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"


def test_non_loopback_runtime_is_refused() -> None:
    try:
        Settings(host="0.0.0.0")
    except ConfigurationError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback host was accepted")
