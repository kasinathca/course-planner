"""Small ASGI security boundary for the loopback-only Phase 0 server."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ffcs_studio.config import Settings


def _hostname(value: str) -> str | None:
    try:
        return urlsplit(f"//{value}").hostname
    except ValueError:
        return None


class LocalSecurityMiddleware:
    """Reject DNS rebinding/cross-origin requests and set local security headers."""

    def __init__(self, app: Any, settings: Settings) -> None:
        self.app = app
        self.settings = settings
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
                if int(content_length) > self.settings.max_request_bytes:
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
        origin = headers.get(b"origin")
        if method not in {"GET", "HEAD", "OPTIONS"} and origin:
            decoded_origin = origin.decode("latin-1").rstrip("/")
            if decoded_origin not in self.allowed_origins:
                await self._json_response(
                    send, 403, "invalid_origin", "Cross-origin request rejected"
                )
                return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
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
                )
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
