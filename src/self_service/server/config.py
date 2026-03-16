"""Runtime configuration for the Coda node server.

Configuration is resolved in three layers (highest priority first):

1. **Environment variables** prefixed with ``CODA_`` (e.g.
   ``CODA_REDIS_URL``).
2. **Persisted runtime config** written to ``/tmp/coda.config`` after a
   successful self-service bootstrap, so later restarts can reconnect
   without a fresh bootstrap token.
3. **Hardcoded defaults** defined on :class:`Settings`.

The persisted private key is stored separately at
``/tmp/coda-private-key`` with ``0600`` permissions on POSIX systems.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from self_service.errors import ConfigError

__all__ = [
    "PERSISTED_CONFIG_PATH",
    "PERSISTED_PRIVATE_KEY_PATH",
    "Settings",
    "load_persisted_runtime_config",
]

_RUNTIME_DIR = Path(tempfile.gettempdir())
PERSISTED_CONFIG_PATH = _RUNTIME_DIR / "coda.config"
PERSISTED_PRIVATE_KEY_PATH = _RUNTIME_DIR / "coda-private-key"


def _read_secure_text(path: Path) -> str:
    """Read a file after verifying it has ``0600`` permissions on POSIX."""
    if not path.exists():
        return ""
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise ConfigError(f"{path} must have permissions 0600")
    return path.read_text()


def load_persisted_runtime_config() -> dict[str, Any]:
    """Load previously persisted runtime state from disk.

    Reads the JSON config at :data:`PERSISTED_CONFIG_PATH` and the
    private key at the path recorded inside it (or the default
    :data:`PERSISTED_PRIVATE_KEY_PATH`).  Both files must have ``0600``
    permissions on POSIX systems or a :class:`ValueError` is raised.

    Returns:
        A dictionary of setting overrides, or an empty dict if no
        persisted config exists.

    Raises:
        ConfigError: If the config file exists but has wrong permissions
            or does not contain a JSON object.
    """
    if not PERSISTED_CONFIG_PATH.exists():
        return {}

    raw_config = _read_secure_text(PERSISTED_CONFIG_PATH)
    if not raw_config.strip():
        return {}

    data = json.loads(raw_config)
    if not isinstance(data, dict):
        raise ConfigError(f"{PERSISTED_CONFIG_PATH} must contain a JSON object")

    private_key_path = Path(
        str(data.get("jwt_private_key_path") or PERSISTED_PRIVATE_KEY_PATH)
    )
    private_key = _read_secure_text(private_key_path)

    persisted: dict[str, Any] = {}
    for key in (
        "qpu_id",
        "qpu_display_name",
        "native_gate_set",
        "num_qubits",
        "jwt_key_id",
        "redis_url",
        "webapp_url",
        "connect_path",
        "register_path",
        "heartbeat_path",
        "webhook_path",
        "vpn_required",
        "vpn_check_interval_sec",
        "vpn_interface_hint",
        "vpn_probe_targets",
        "self_service_auto_vpn",
        "self_service_vpn_profile_path",
        "advertised_provider",
        "opx_host",
        "opx_port",
        "self_service_machine_fingerprint",
    ):
        if key in data:
            persisted[key] = data[key]

    if private_key:
        persisted["jwt_private_key"] = private_key

    return persisted


class Settings(BaseSettings):
    """Coda-connected node configuration.

    All fields can be set via ``CODA_``-prefixed environment variables
    (e.g. ``CODA_QPU_ID``, ``CODA_REDIS_URL``).  When no self-service
    token is provided, the model validator automatically loads any
    previously persisted runtime config so the node can reconnect with
    its stored JWT credentials.

    The model uses ``validate_assignment=True`` so that mutations made
    by :func:`~self_service.vpn.service.apply_self_service_bundle` are
    validated against field types.
    """

    qpu_id: str = ""
    qpu_display_name: str = ""
    native_gate_set: str = "superconducting_cz"
    num_qubits: int = 5

    redis_url: str = ""

    jwt_private_key: str = ""
    jwt_key_id: str = ""

    webapp_url: str = ""
    webhook_path: str = "/api/internal/qpu/webhook"
    connect_path: str = "/api/internal/qpu/connect"
    register_path: str = "/api/internal/qpu/register"
    heartbeat_path: str = "/api/internal/qpu/heartbeat"
    self_service_path: str = "/api/internal/qpu/self-service"

    host: str = "0.0.0.0"
    port: int = 8080

    vpn_required: bool = True
    vpn_check_interval_sec: int = 10
    vpn_probe_targets: list[str] = []
    vpn_interface_hint: str | None = None
    allow_degraded_startup: bool = False

    self_service_token: str = ""
    self_service_timeout_sec: int = 15
    self_service_machine_fingerprint: str = ""
    self_service_auto_vpn: bool = True
    self_service_vpn_profile_path: str = (
        f"{tempfile.gettempdir()}/coda-self-service.ovpn"
    )

    self_service_connect_retries: int = 3
    shutdown_drain_timeout_sec: int = 30

    executor_factory: str = ""
    advertised_provider: str = "coda"

    opx_host: str = "localhost"
    opx_port: int = 80

    @model_validator(mode="before")
    @classmethod
    def merge_persisted_runtime_config(cls, data: Any) -> Any:
        """Apply persisted runtime config before field validation.

        This preserves the intended precedence order without mutating the model
        during validation, which would otherwise re-enter assignment validation.
        """
        if not isinstance(data, dict):
            return data
        if data.get("self_service_token"):
            return data

        merged = dict(data)
        persisted = load_persisted_runtime_config()
        for key, value in persisted.items():
            current = merged.get(key)
            if key not in merged or current in ("", None, []):
                merged[key] = value
        return merged

    @model_validator(mode="after")
    def check_jwt_or_self_service(self) -> Settings:
        """Require JWT credentials unless self-service will supply them."""

        if not self.self_service_token:
            if not self.jwt_private_key:
                raise ValueError(
                    "CODA_JWT_PRIVATE_KEY must be set "
                    "(or provide CODA_SELF_SERVICE_TOKEN for auto-provisioning)"
                )
            if not self.jwt_key_id:
                raise ValueError(
                    "CODA_JWT_KEY_ID must be set "
                    "(or provide CODA_SELF_SERVICE_TOKEN for auto-provisioning)"
                )
        return self

    @property
    def callback_url(self) -> str:
        """Full URL for webhook delivery."""
        return f"{self.webapp_url}{self.webhook_path}"

    @property
    def register_url(self) -> str:
        """Full URL for QPU registration."""
        return f"{self.webapp_url}{self.register_path}"

    @property
    def connect_url(self) -> str:
        """Full URL for the self-service connect endpoint."""
        return f"{self.webapp_url}{self.connect_path}"

    @property
    def heartbeat_url(self) -> str:
        """Full URL for heartbeat reporting."""
        return f"{self.webapp_url}{self.heartbeat_path}"

    @property
    def vpn_probe_urls(self) -> list[str]:
        """URLs to probe for VPN connectivity, falling back to API endpoints."""
        if self.vpn_probe_targets:
            return list(self.vpn_probe_targets)
        return [self.connect_url, self.heartbeat_url]

    model_config = SettingsConfigDict(env_prefix="CODA_", validate_assignment=True)
