"""Loopback Host, request-size, same-origin, and CSRF ASGI boundary."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast
from urllib.parse import urlsplit

from ffcs_studio.config import Settings

SECURITY_HEADERS = [
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self'; "
        b"img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        b"frame-ancestors 'none'; form-action 'self'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


class RequestBodyTooLarge(Exception):
    """Raised before an excessive request chunk reaches the application."""


def _hostname(value: str) -> str | None:
    if not value or any(character.isspace() for character in value):
        return None
    if any(character in value for character in "/?#@"):
        return None
    try:
        return urlsplit(f"//{value}").hostname
    except ValueError:
        return None


class LocalSecurityMiddleware:
    """Reject DNS rebinding/cross-origin requests and set local security headers."""

    def __init__(self, app: Any, settings: Settings, csrf_token: str) -> None:
        self.app = app
        self.settings = settings
        self.csrf_token = csrf_token
        self.allowed_hosts = {"127.0.0.1", "localhost", "::1"}
        self.allowed_origins = {
            f"http://127.0.0.1:{settings.port}",
            f"http://localhost:{settings.port}",
            f"http://[::1]:{settings.port}",
        }

    async def _json_response(
        self,
        send: Any,
        status: int,
        code: str,
        message: str,
    ) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                    *SECURITY_HEADERS,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host_header = headers.get(b"host", b"").decode("latin-1")
        host = _hostname(host_header)
        if host is None or host.lower() not in self.allowed_hosts:
            await self._json_response(send, 400, "invalid_host", "Host is not allowed")
            return

        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_length = int(content_length)
                if declared_length < 0:
                    raise ValueError
                if declared_length > self.settings.max_request_bytes:
                    await self._json_response(
                        send, 413, "request_too_large", "Request body is too large"
                    )
                    return
            except ValueError:
                await self._json_response(
                    send, 400, "invalid_content_length", "Content-Length is invalid"
                )
                return

        method = scope.get("method", "GET").upper()
        if method not in {"GET", "HEAD", "OPTIONS"}:
            fetch_site = headers.get(b"sec-fetch-site")
            if fetch_site and fetch_site.decode("latin-1").lower() not in {
                "same-origin",
                "none",
            }:
                await self._json_response(
                    send, 403, "invalid_request_site", "Cross-site request rejected"
                )
                return
            origin = headers.get(b"origin")
            if origin and origin.decode("latin-1").rstrip("/") not in self.allowed_origins:
                await self._json_response(
                    send, 403, "invalid_origin", "Cross-origin request rejected"
                )
                return
            referer = headers.get(b"referer")
            if referer and _origin_from_url(referer.decode("latin-1")) not in self.allowed_origins:
                await self._json_response(
                    send, 403, "invalid_referer", "Cross-origin request rejected"
                )
                return
            supplied_csrf = headers.get(b"x-ffcs-csrf", b"").decode("latin-1")
            if not supplied_csrf or not secrets.compare_digest(supplied_csrf, self.csrf_token):
                await self._json_response(
                    send, 403, "invalid_csrf", "Write authorization is missing or invalid"
                )
                return

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > self.settings.max_request_bytes:
                    raise RequestBodyTooLarge
            return cast(dict[str, Any], message)

        response_started = False

        async def send_with_headers(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = list(message.get("headers", []))
                response_headers.extend(SECURITY_HEADERS)
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, limited_receive, send_with_headers)
        except RequestBodyTooLarge:
            if not response_started:
                await self._json_response(
                    send, 413, "request_too_large", "Request body is too large"
                )


def _origin_from_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}"
