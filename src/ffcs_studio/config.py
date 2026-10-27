"""Environment-backed runtime configuration with loopback-safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when local runtime configuration is unsafe or malformed."""


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "FFCSStudio"
    return Path.home() / ".ffcs-studio"


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated server settings with a deliberately loopback-only host."""

    host: str = "127.0.0.1"
    port: int = 8765
    max_request_bytes: int = 1_048_576
    data_dir: Path = field(default_factory=_default_data_dir)

    def __post_init__(self) -> None:
        if not _is_loopback_host(self.host):
            raise ConfigurationError(
                f"FFCS Studio may only bind to a loopback host; received {self.host!r}"
            )
        if not 1 <= self.port <= 65_535:
            raise ConfigurationError("port must be between 1 and 65535")
        if self.max_request_bytes < 1_024:
            raise ConfigurationError("max_request_bytes must be at least 1024")

    @classmethod
    def from_env(
        cls,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> Settings:
        """Build settings from explicit CLI values over environment defaults."""

        env_port = os.environ.get("FFCS_STUDIO_PORT", "8765")
        env_limit = os.environ.get("FFCS_STUDIO_MAX_REQUEST_BYTES", "1048576")
        try:
            resolved_port = port if port is not None else int(env_port)
            request_limit = int(env_limit)
        except ValueError as exc:
            raise ConfigurationError("port and request limit must be integers") from exc

        data_dir = Path(os.environ.get("FFCS_STUDIO_DATA_DIR", _default_data_dir()))
        return cls(
            host=host or os.environ.get("FFCS_STUDIO_HOST", "127.0.0.1"),
            port=resolved_port,
            max_request_bytes=request_limit,
            data_dir=data_dir,
        )

    @property
    def base_url(self) -> str:
        display_host = (
            f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        )
        return f"http://{display_host}:{self.port}"
