"""Runtime configuration for the Coda node server.

Configuration is resolved in three layers (highest priority first):

1. **Environment variables** prefixed with ``CODA_`` (e.g.
   ``CODA_REDIS_URL``).
2. **Persisted runtime config** written to ``/tmp/coda.config`` after a
   successful node provisioning, so later restarts can reconnect
   without a fresh token.
3. **Hardcoded defaults** defined on :class:`Settings`.

The persisted private key is stored separately at
``/tmp/coda-private-key`` with ``0600`` permissions on POSIX systems.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from coda_node.errors import ConfigError

logger = logging.getLogger(__name__)
_EXECUTOR_FACTORY_RE = re.compile(r"^executor_factory\s*:\s*(.+?)\s*$")

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
        "heartbeat_path",
        "webhook_path",
        "vpn_required",
        "vpn_check_interval_sec",
        "vpn_interface_hint",
        "vpn_probe_targets",
        "node_auto_vpn",
        "node_vpn_profile_path",
        "node_machine_fingerprint",
    ):
        if key in data:
            persisted[key] = data[key]

    if private_key:
        persisted["jwt_private_key"] = private_key

    return persisted


def _strip_inline_yaml_comment(value: str) -> str:
    """Remove trailing comments from a simple scalar YAML value."""
    in_single = False
    in_double = False
    for idx, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return value[:idx].rstrip()
    return value.strip()


def _load_executor_factory_from_device_config(path: str) -> str:
    """Read an optional top-level ``executor_factory`` scalar from device YAML."""
    try:
        for raw_line in Path(path).read_text().splitlines():
            if raw_line.startswith((" ", "\t")):
                continue
            match = _EXECUTOR_FACTORY_RE.match(raw_line.strip())
            if not match:
                continue
            value = _strip_inline_yaml_comment(match.group(1))
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value.strip()
    except OSError:
        logger.warning(
            "Failed to read device config while resolving executor factory: %s", path
        )
    return ""


class Settings(BaseSettings):
    """Coda-connected node configuration.

    All fields can be set via ``CODA_``-prefixed environment variables
    (e.g. ``CODA_QPU_ID``, ``CODA_REDIS_URL``).  When no node
    token is provided, the model validator automatically loads any
    previously persisted runtime config so the node can reconnect with
    its stored JWT credentials.

    The model uses ``validate_assignment=True`` so that mutations made
    by :func:`~coda_node.vpn.service.apply_node_bundle` are
    validated against field types.
    """

    qpu_id: str = ""
    qpu_display_name: str = ""
    native_gate_set: str = "cz"
    num_qubits: int = 5

    redis_url: str = ""

    jwt_private_key: str = ""
    jwt_key_id: str = ""

    webapp_url: str = "https://coda.conductorquantum.com"
    webhook_path: str = "/api/internal/qpu/webhook"
    connect_path: str = "/api/internal/qpu/connect"
    heartbeat_path: str = "/api/internal/qpu/heartbeat"

    host: str = "0.0.0.0"
    port: int = 8080

    vpn_required: bool = True
    vpn_check_interval_sec: int = 10
    vpn_probe_targets: list[str] = []
    vpn_interface_hint: str | None = None
    allow_degraded_startup: bool = False

    node_token: str = ""
    node_timeout_sec: int = 15
    node_machine_fingerprint: str = ""
    node_auto_vpn: bool = True
    node_vpn_profile_path: str = f"{tempfile.gettempdir()}/coda-node.ovpn"

    node_connect_headers: dict[str, str] = {}
    node_connect_retries: int = 3
    shutdown_drain_timeout_sec: int = 30
    heartbeat_interval_sec: int = 30

    executor_factory: str = ""
    device_config: str = ""
    advertised_provider: str = "coda"

    @model_validator(mode="before")
    @classmethod
    def merge_persisted_runtime_config(cls, data: Any) -> Any:
        """Apply persisted runtime config before field validation.

        This preserves the intended precedence order without mutating the model
        during validation, which would otherwise re-enter assignment validation.
        """
        if not isinstance(data, dict):
            return data
        if data.get("node_token"):
            return data

        merged = dict(data)
        persisted = load_persisted_runtime_config()
        for key, value in persisted.items():
            current = merged.get(key)
            if key not in merged or current in ("", None, []):
                merged[key] = value
        return merged

    @model_validator(mode="after")
    def apply_default_device_config(self) -> Settings:
        """Use ``./site/device.yaml`` when no explicit device config is set."""
        if not self.device_config:
            default_path = Path("site/device.yaml")
            if default_path.exists():
                logger.info("Using default device config: %s", default_path)
                self.device_config = default_path.as_posix()
        return self

    @model_validator(mode="after")
    def apply_device_config_executor_factory(self) -> Settings:
        """Use ``executor_factory`` from the device config when env/config omit it."""
        if self.executor_factory or not self.device_config:
            return self

        resolved = _load_executor_factory_from_device_config(self.device_config)
        if resolved:
            logger.info(
                "Using executor factory from device config %s: %s",
                self.device_config,
                resolved,
            )
            self.executor_factory = resolved
        return self

    @model_validator(mode="after")
    def check_jwt_or_node_token(self) -> Settings:
        """Require JWT credentials unless node will supply them."""

        if not self.node_token:
            if not self.jwt_private_key:
                raise ValueError(
                    "CODA_JWT_PRIVATE_KEY must be set "
                    "(or provide CODA_NODE_TOKEN for auto-provisioning)"
                )
            if not self.jwt_key_id:
                raise ValueError(
                    "CODA_JWT_KEY_ID must be set "
                    "(or provide CODA_NODE_TOKEN for auto-provisioning)"
                )
        return self

    @property
    def callback_url(self) -> str:
        """Full URL for webhook delivery."""
        return f"{self.webapp_url}{self.webhook_path}"

    @property
    def connect_url(self) -> str:
        """Full URL for the node connect endpoint."""
        return f"{self.webapp_url}{self.connect_path}"

    @property
    def heartbeat_url(self) -> str:
        """Full URL for heartbeat reporting."""
        return f"{self.webapp_url}{self.heartbeat_path}"

    @property
    def vpn_probe_urls(self) -> list[str]:
        """URLs to probe for VPN connectivity.

        Returns explicit targets when configured, the health endpoint as
        a fallback when VPN is required, or an empty list when VPN is
        not required (HTTPS mode) to avoid probing endpoints that only
        accept POST.
        """
        if self.vpn_probe_targets:
            return list(self.vpn_probe_targets)
        if not self.vpn_required:
            return []
        return [f"{self.webapp_url}/api/internal/qpu/health"]

    model_config = SettingsConfigDict(env_prefix="CODA_", validate_assignment=True)
