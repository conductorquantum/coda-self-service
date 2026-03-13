"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

_RUNTIME_DIR = Path(tempfile.gettempdir())
PERSISTED_CONFIG_PATH = _RUNTIME_DIR / "coda.config"
PERSISTED_PRIVATE_KEY_PATH = _RUNTIME_DIR / "coda-private-key"


def _read_secure_text(path: Path) -> str:
    if not path.exists():
        return ""
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise ValueError(f"{path} must have permissions 0600")
    return path.read_text()


def load_persisted_runtime_config() -> dict[str, Any]:
    if not PERSISTED_CONFIG_PATH.exists():
        return {}

    raw_config = _read_secure_text(PERSISTED_CONFIG_PATH)
    if not raw_config.strip():
        return {}

    data = json.loads(raw_config)
    if not isinstance(data, dict):
        raise ValueError(f"{PERSISTED_CONFIG_PATH} must contain a JSON object")

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
    ):
        if key in data:
            persisted[key] = data[key]

    if private_key:
        persisted["jwt_private_key"] = private_key

    return persisted


class Settings(BaseSettings):
    """Coda-connected node configuration."""

    qpu_id: str = ""
    qpu_display_name: str = ""
    native_gate_set: str = "superconducting_cz"
    num_qubits: int = 5

    redis_url: str = ""

    jwt_private_key: str = ""
    jwt_key_id: str = ""

    webapp_url: str = Field(
        default="https://blythe-unnourished-semicynically.ngrok-free.dev",
        validation_alias="CODA_WEBAPP_URL",
    )
    webhook_path: str = "/api/internal/qpu/webhook"
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

    executor_factory: str = ""
    advertised_provider: str = "coda"

    opx_host: str = "localhost"
    opx_port: int = 80

    @model_validator(mode="after")
    def check_jwt_or_self_service(self) -> Settings:
        """Require JWT credentials unless self-service will supply them."""
        if not self.self_service_token:
            persisted = load_persisted_runtime_config()
            for key, value in persisted.items():
                current = getattr(self, key)
                if key not in self.model_fields_set or current in ("", None, []):
                    setattr(self, key, value)

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
        return f"{self.webapp_url}{self.webhook_path}"

    @property
    def register_url(self) -> str:
        return f"{self.webapp_url}{self.register_path}"

    @property
    def heartbeat_url(self) -> str:
        return f"{self.webapp_url}{self.heartbeat_path}"

    @property
    def vpn_probe_urls(self) -> list[str]:
        if self.vpn_probe_targets:
            return list(self.vpn_probe_targets)
        return [self.register_url, self.heartbeat_url]

    model_config = {"env_prefix": "CODA_"}
