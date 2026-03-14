"""Self-service provisioning, credential persistence, and OpenVPN management.

This module implements the full bootstrap and reconnect lifecycle:

1. **First run** -- the operator provides a one-time ``CODA_SELF_SERVICE_TOKEN``.
   The runtime POSTs to ``/api/internal/qpu/connect`` with the token,
   receives a bundle containing JWT credentials, Redis URL, API paths,
   and optionally a VPN client profile.
2. **VPN setup** -- if the bundle includes a profile, the runtime
   writes it to disk (after sanitizing dangerous directives), launches
   an OpenVPN daemon, and polls for a tunnel interface.
3. **Persistence** -- credentials and config are written to disk with
   ``0600`` permissions so the next restart can reconnect without a
   fresh token.
4. **Reconnect** -- on subsequent starts, the runtime reads persisted
   state, brings up the VPN tunnel, and authenticates with its stored
   JWT key.

Security notes:

* VPN profiles are scanned for shell-execution directives (``up``,
  ``down``, ``plugin``, etc.) and rejected if any are found.
* Private keys and config files are written with ``0600`` permissions
  and validated on read.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx

if TYPE_CHECKING:
    from self_service.server.config import Settings

from self_service.server.auth import sign_token
from self_service.server.config import PERSISTED_CONFIG_PATH, PERSISTED_PRIVATE_KEY_PATH

logger = logging.getLogger(__name__)

_RUNTIME_DIR = Path(tempfile.gettempdir())
OPENVPN_PID_PATH = _RUNTIME_DIR / "coda-self-service-openvpn.pid"
OPENVPN_LOG_PATH = _RUNTIME_DIR / "coda-self-service-openvpn.log"

_TUNNEL_POLL_INTERVAL = 1.0
_TUNNEL_TIMEOUT = 30.0


class SelfServiceError(RuntimeError):
    """Raised when self-service provisioning or VPN setup fails.

    Covers token validation errors, HTTP failures from the Coda API,
    missing VPN profiles, OpenVPN launch failures, and tunnel timeouts.
    """


def _machine_fingerprint() -> str:
    return f"{socket.gethostname()}-{uuid.getnode()}"


_DANGEROUS_OVPN_DIRECTIVES = frozenset(
    {
        "script-security",
        "up",
        "down",
        "client-connect",
        "client-disconnect",
        "learn-address",
        "auth-user-pass-verify",
        "tls-verify",
        "ipchange",
        "route-up",
        "route-pre-down",
        "plugin",
    }
)


def _validate_vpn_profile(profile: str) -> None:
    for lineno, line in enumerate(profile.splitlines(), 1):
        directive = line.strip().split()[0].lower() if line.strip() else ""
        if directive in _DANGEROUS_OVPN_DIRECTIVES:
            raise SelfServiceError(
                f"Refusing OpenVPN profile: forbidden directive '{directive}' on line {lineno}"
            )


def _write_vpn_profile(path: str, profile: str) -> None:
    _validate_vpn_profile(profile)
    profile_path = Path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    _write_secure_text(profile_path, profile)


def _write_secure_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if os.name != "nt":
        path.chmod(0o600)


def _persist_runtime_config(settings: Settings) -> None:
    _write_secure_text(PERSISTED_PRIVATE_KEY_PATH, settings.jwt_private_key)

    persisted = {
        "qpu_id": settings.qpu_id,
        "qpu_display_name": settings.qpu_display_name,
        "native_gate_set": settings.native_gate_set,
        "num_qubits": settings.num_qubits,
        "jwt_key_id": settings.jwt_key_id,
        "jwt_private_key_path": str(PERSISTED_PRIVATE_KEY_PATH),
        "redis_url": settings.redis_url,
        "webapp_url": settings.webapp_url,
        "connect_path": settings.connect_path,
        "register_path": settings.register_path,
        "heartbeat_path": settings.heartbeat_path,
        "webhook_path": settings.webhook_path,
        "vpn_required": settings.vpn_required,
        "vpn_check_interval_sec": settings.vpn_check_interval_sec,
        "vpn_interface_hint": settings.vpn_interface_hint,
        "vpn_probe_targets": settings.vpn_probe_targets,
        "self_service_auto_vpn": settings.self_service_auto_vpn,
        "self_service_vpn_profile_path": settings.self_service_vpn_profile_path,
        "advertised_provider": settings.advertised_provider,
        "opx_host": settings.opx_host,
        "opx_port": settings.opx_port,
        "self_service_machine_fingerprint": settings.self_service_machine_fingerprint,
    }
    _write_secure_text(PERSISTED_CONFIG_PATH, json.dumps(persisted, indent=2) + "\n")


def _openvpn_binary() -> str | None:
    return shutil.which("openvpn") or shutil.which("openvpn.exe")


def _start_openvpn(profile_path: str) -> None:
    openvpn_bin = _openvpn_binary()
    if openvpn_bin is None:
        raise SelfServiceError(
            "openvpn binary not found. Install OpenVPN or disable self-service auto VPN."
        )

    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log_handle = OPENVPN_LOG_PATH.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [
                    openvpn_bin,
                    "--config",
                    profile_path,
                    "--log",
                    str(OPENVPN_LOG_PATH),
                ],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        finally:
            log_handle.close()
        OPENVPN_PID_PATH.write_text(f"{process.pid}\n")
        return

    result = subprocess.run(
        [
            openvpn_bin,
            "--config",
            profile_path,
            "--daemon",
            "--writepid",
            str(OPENVPN_PID_PATH),
            "--log",
            str(OPENVPN_LOG_PATH),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise SelfServiceError(
            f"Failed to start OpenVPN: {result.stderr.strip() or 'unknown openvpn error'}"
        )


def _read_openvpn_log_tail(max_lines: int = 20) -> str:
    try:
        lines = OPENVPN_LOG_PATH.read_text().splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def kill_openvpn_daemon() -> bool:
    """Terminate the managed OpenVPN daemon and clean up its PID file.

    Uses ``SIGTERM`` on POSIX and ``taskkill`` on Windows.  Silently
    succeeds if the process is already gone.

    Returns:
        ``True`` if a process was found and signalled, ``False`` if no
        PID file existed.
    """
    if not OPENVPN_PID_PATH.exists():
        return False

    try:
        pid = int(OPENVPN_PID_PATH.read_text().strip())
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        OPENVPN_PID_PATH.unlink(missing_ok=True)
        return True
    except (PermissionError, ProcessLookupError, ValueError, subprocess.TimeoutExpired):
        OPENVPN_PID_PATH.unlink(missing_ok=True)
        return False


async def _wait_for_tunnel(
    hint: str | None = None,
    timeout: float = _TUNNEL_TIMEOUT,
    poll_interval: float = _TUNNEL_POLL_INTERVAL,
) -> str:
    from self_service.vpn.guard import _detect_tun_interface

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        iface = await asyncio.to_thread(_detect_tun_interface, hint)
        if iface is not None:
            return iface
        await asyncio.sleep(poll_interval)

    detail = _read_openvpn_log_tail()
    kill_openvpn_daemon()
    log_tail = f"\nOpenVPN log tail:\n{detail}" if detail else ""
    raise SelfServiceError(
        f"OpenVPN daemon started but no VPN tunnel interface appeared within {timeout}s. "
        f"Check firewall rules and VPN endpoint connectivity.{log_tail}"
    )


def _as_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SelfServiceError(f"Self-service response missing valid '{key}'")
    return value


def _as_int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, int):
        return value
    raise SelfServiceError(f"Self-service response has invalid '{key}'")


def _resolve_machine_fingerprint(settings: Settings) -> str:
    fingerprint = settings.self_service_machine_fingerprint or _machine_fingerprint()
    settings.self_service_machine_fingerprint = fingerprint
    return fingerprint


async def _post_connect(
    settings: Settings, *, auth_header: str, payload: dict[str, Any]
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=settings.self_service_timeout_sec) as client:
        response = await client.post(
            settings.connect_url,
            json=payload,
            headers={"Authorization": auth_header},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SelfServiceError(
                f"Self-service request failed ({response.status_code}): {response.text[:400]}"
            ) from exc
        return cast(dict[str, Any], response.json())


async def fetch_self_service_bundle(settings: Settings) -> dict[str, Any]:
    """Fetch the provisioning bundle using a one-time bootstrap token.

    POSTs the machine fingerprint and OPX connection details to the
    Coda connect endpoint.  The returned bundle contains JWT keys,
    Redis URL, API paths, and optional VPN configuration.

    Args:
        settings: Runtime settings (must have a non-empty
            ``self_service_token``).

    Returns:
        The raw bundle dictionary from the Coda API.

    Raises:
        SelfServiceError: If the token is empty or the HTTP request fails.
    """
    if not settings.self_service_token:
        raise SelfServiceError("self-service token is empty")

    payload = {
        "machine_fingerprint": _resolve_machine_fingerprint(settings),
        "opx_host": settings.opx_host,
        "opx_port": settings.opx_port,
    }
    return await _post_connect(
        settings,
        auth_header=f"Bearer {settings.self_service_token}",
        payload=payload,
    )


async def fetch_reconnect_bundle(settings: Settings) -> dict[str, Any]:
    """Fetch a reconnect bundle using stored JWT credentials.

    Authenticates with a freshly signed JWT (instead of a bootstrap
    token) to get an updated bundle.  The server may refresh Redis
    URLs, API paths, or VPN configuration.

    Args:
        settings: Runtime settings with valid ``jwt_private_key`` and
            ``jwt_key_id``.

    Returns:
        The raw bundle dictionary from the Coda API.

    Raises:
        SelfServiceError: If the HTTP request fails.
    """
    payload = {
        "machine_fingerprint": _resolve_machine_fingerprint(settings),
        "opx_host": settings.opx_host,
        "opx_port": settings.opx_port,
    }
    token = sign_token(
        settings.qpu_id,
        settings.jwt_private_key,
        key_id=settings.jwt_key_id,
    )
    return await _post_connect(
        settings,
        auth_header=f"Bearer {token}",
        payload=payload,
    )


async def apply_self_service_bundle(settings: Settings, bundle: dict[str, Any]) -> None:
    """Apply a self-service bundle to the runtime settings.

    Mutates *settings* in place with QPU identity, JWT credentials,
    Redis URL, API paths, and VPN configuration from the bundle.  If
    ``self_service_auto_vpn`` is enabled and the bundle includes a VPN
    profile, the profile is written to disk and an OpenVPN daemon is
    started (unless a tunnel is already active).

    Args:
        settings: The mutable runtime settings object.
        bundle: Raw JSON bundle from :func:`fetch_self_service_bundle`
            or :func:`fetch_reconnect_bundle`.

    Raises:
        SelfServiceError: If required fields are missing or the VPN
            setup fails.
    """
    settings.qpu_id = _as_str(bundle, "qpu_id")
    settings.qpu_display_name = _as_str(bundle, "qpu_display_name")
    settings.native_gate_set = _as_str(bundle, "native_gate_set")
    settings.num_qubits = _as_int(bundle, "num_qubits", settings.num_qubits)
    jwt_private_key = bundle.get("jwt_private_key")
    if isinstance(jwt_private_key, str) and jwt_private_key:
        settings.jwt_private_key = jwt_private_key
    elif not settings.jwt_private_key:
        raise SelfServiceError("Self-service response missing valid 'jwt_private_key'")

    jwt_key_id = bundle.get("jwt_key_id")
    if isinstance(jwt_key_id, str) and jwt_key_id:
        settings.jwt_key_id = jwt_key_id
    elif not settings.jwt_key_id:
        raise SelfServiceError("Self-service response missing valid 'jwt_key_id'")

    settings.redis_url = _as_str(bundle, "redis_url")
    settings.webapp_url = _as_str(
        bundle,
        "webapp_url" if "webapp_url" in bundle else "cloud_base_url",
    )

    connect_path = bundle.get("connect_path")
    if isinstance(connect_path, str) and connect_path:
        settings.connect_path = connect_path

    register_path = bundle.get("register_path")
    if isinstance(register_path, str) and register_path:
        settings.register_path = register_path

    heartbeat_path = bundle.get("heartbeat_path")
    if isinstance(heartbeat_path, str) and heartbeat_path:
        settings.heartbeat_path = heartbeat_path

    webhook_path = bundle.get("webhook_path")
    if isinstance(webhook_path, str) and webhook_path:
        settings.webhook_path = webhook_path

    vpn = bundle.get("vpn")
    if isinstance(vpn, dict):
        required = vpn.get("required")
        interface_hint = vpn.get("interface_hint")
        interval = vpn.get("check_interval_sec")
        probe_targets = vpn.get("probe_targets")
        profile = vpn.get("client_profile_ovpn")

        if isinstance(required, bool):
            settings.vpn_required = required
        if interface_hint is None or isinstance(interface_hint, str):
            settings.vpn_interface_hint = interface_hint
        if isinstance(interval, int):
            settings.vpn_check_interval_sec = interval
        if (
            isinstance(probe_targets, list)
            and all(isinstance(item, str) for item in probe_targets)
            and probe_targets
        ):
            settings.vpn_probe_targets = cast(list[str], probe_targets)

        if settings.vpn_required and (not isinstance(profile, str) or not profile):
            raise SelfServiceError(
                "VPN is required but self-service response did not include a VPN profile. "
                "Check VPN infrastructure status in the coda admin panel."
            )

        if settings.self_service_auto_vpn and isinstance(profile, str) and profile:
            await asyncio.to_thread(
                _write_vpn_profile, settings.self_service_vpn_profile_path, profile
            )
            from self_service.vpn.guard import _detect_tun_interface

            iface = await asyncio.to_thread(
                _detect_tun_interface, settings.vpn_interface_hint
            )
            if iface is None:
                await asyncio.to_thread(
                    _start_openvpn, settings.self_service_vpn_profile_path
                )
                await _wait_for_tunnel(hint=settings.vpn_interface_hint)


async def connect_settings(settings: Settings) -> None:
    """Bootstrap or reconnect the node to the Coda cloud.

    On first run (token present), fetches a self-service bundle.  On
    subsequent runs (no token), restores the persisted VPN tunnel and
    fetches a reconnect bundle with stored JWT credentials.

    After the bundle is applied and config is persisted, any failure
    triggers cleanup of a potentially half-started VPN daemon.

    Args:
        settings: Runtime settings to populate.

    Raises:
        SelfServiceError: On bootstrap or reconnect failure.
    """
    _resolve_machine_fingerprint(settings)
    if settings.self_service_token:
        bundle = await fetch_self_service_bundle(settings)
    else:
        await ensure_persisted_vpn(settings)
        bundle = await fetch_reconnect_bundle(settings)
    try:
        await apply_self_service_bundle(settings, bundle)
        await asyncio.to_thread(_persist_runtime_config, settings)
    except Exception:
        if settings.self_service_token:
            kill_openvpn_daemon()
        raise


async def self_service_settings(settings: Settings) -> None:
    """Alias for :func:`connect_settings` (backward compatibility)."""
    await connect_settings(settings)


async def ensure_persisted_vpn(settings: Settings) -> None:
    """Restore a previously configured VPN tunnel for reconnect.

    If a persisted config and VPN profile exist, and no tunnel is
    currently active, starts an OpenVPN daemon and waits for the
    interface to come up.  No-ops if auto VPN is disabled or no
    persisted config is found.

    Args:
        settings: Runtime settings with VPN profile path and interface
            hint.

    Raises:
        SelfServiceError: If VPN is required but the persisted profile
            is missing, or if the tunnel fails to come up.
    """
    if not PERSISTED_CONFIG_PATH.exists():
        return

    if not settings.self_service_auto_vpn:
        return

    profile_path = Path(settings.self_service_vpn_profile_path)
    if not profile_path.exists():
        if settings.vpn_required:
            raise SelfServiceError(
                "Persisted VPN profile not found. Re-run self-service bootstrap with a new token."
            )
        return

    from self_service.vpn.guard import _detect_tun_interface

    iface = await asyncio.to_thread(_detect_tun_interface, settings.vpn_interface_hint)
    if iface is not None:
        return

    await asyncio.to_thread(_start_openvpn, settings.self_service_vpn_profile_path)
    await _wait_for_tunnel(hint=settings.vpn_interface_hint)
