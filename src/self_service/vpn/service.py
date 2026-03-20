"""Self-service provisioning, credential persistence, and OpenVPN management.

This module implements the full self-service and reconnect lifecycle:

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

from self_service.errors import SelfServiceError
from self_service.server.auth import sign_token
from self_service.server.config import PERSISTED_CONFIG_PATH, PERSISTED_PRIVATE_KEY_PATH

logger = logging.getLogger(__name__)

__all__ = [
    "OPENVPN_LOG_PATH",
    "OPENVPN_PID_PATH",
    "SelfServiceError",
    "apply_self_service_bundle",
    "connect_settings",
    "ensure_persisted_vpn",
    "fetch_reconnect_bundle",
    "fetch_self_service_bundle",
    "kill_openvpn_daemon",
    "self_service_settings",
]

_RUNTIME_DIR = Path(tempfile.gettempdir())
OPENVPN_PID_PATH = _RUNTIME_DIR / "coda-self-service-openvpn.pid"
OPENVPN_LOG_PATH = _RUNTIME_DIR / "coda-self-service-openvpn.log"

_TUNNEL_POLL_INTERVAL = 1.0
_TUNNEL_TIMEOUT = 30.0


def _machine_fingerprint() -> str:
    """Generate a stable machine identifier from hostname and MAC address."""
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
    """Reject OpenVPN profiles containing dangerous shell-execution directives."""
    for lineno, line in enumerate(profile.splitlines(), 1):
        directive = line.strip().split()[0].lower() if line.strip() else ""
        if directive in _DANGEROUS_OVPN_DIRECTIVES:
            raise SelfServiceError(
                f"Refusing OpenVPN profile: forbidden directive '{directive}' on line {lineno}"
            )


def _write_vpn_profile(path: str, profile: str) -> None:
    """Validate and write an OpenVPN profile to *path* with secure permissions."""
    _validate_vpn_profile(profile)
    if "reneg-sec" not in profile:
        profile = profile.rstrip() + "\nreneg-sec 0\n"
    profile_path = Path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    _write_secure_text(profile_path, profile)


def _write_secure_text(path: Path, content: str) -> None:
    """Write *content* to *path* and restrict permissions to ``0600`` on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if os.name != "nt":
        path.chmod(0o600)


def _persist_runtime_config(settings: Settings) -> None:
    """Write the private key and runtime config to disk for future reconnects."""
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
        "heartbeat_path": settings.heartbeat_path,
        "webhook_path": settings.webhook_path,
        "vpn_required": settings.vpn_required,
        "vpn_check_interval_sec": settings.vpn_check_interval_sec,
        "vpn_interface_hint": settings.vpn_interface_hint,
        "vpn_probe_targets": settings.vpn_probe_targets,
        "self_service_auto_vpn": settings.self_service_auto_vpn,
        "self_service_vpn_profile_path": settings.self_service_vpn_profile_path,
        "self_service_machine_fingerprint": settings.self_service_machine_fingerprint,
    }
    _write_secure_text(PERSISTED_CONFIG_PATH, json.dumps(persisted, indent=2) + "\n")


def _openvpn_binary() -> str | None:
    """Locate the ``openvpn`` binary on ``$PATH``."""
    return shutil.which("openvpn") or shutil.which("openvpn.exe")


def _start_openvpn(profile_path: str) -> None:
    """Launch an OpenVPN daemon in the background using *profile_path*."""
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
    """Return the last *max_lines* of the OpenVPN log, or empty string on error."""
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
    """Poll until a VPN tunnel interface appears or *timeout* expires."""
    from self_service.vpn.guard import detect_tun_interface

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        iface = await asyncio.to_thread(detect_tun_interface, hint)
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
    """Extract a required non-empty string from *data* or raise."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SelfServiceError(f"Self-service response missing valid '{key}'")
    return value


def _as_int(data: dict[str, Any], key: str, default: int) -> int:
    """Extract an integer from *data*, falling back to *default*."""
    value = data.get(key, default)
    if isinstance(value, int):
        return value
    raise SelfServiceError(f"Self-service response has invalid '{key}'")


def _resolve_machine_fingerprint(settings: Settings) -> str:
    """Return the machine fingerprint, generating and storing one if absent."""
    fingerprint = settings.self_service_machine_fingerprint or _machine_fingerprint()
    settings.self_service_machine_fingerprint = fingerprint
    return fingerprint


async def _post_connect(
    settings: Settings,
    *,
    auth_header: str,
    payload: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    """POST to the connect endpoint with exponential-backoff retry.

    Retries on 5xx and transport errors up to *max_retries* times.
    Client errors (4xx) are raised immediately as
    :class:`SelfServiceError`.

    Args:
        settings: Runtime settings (used for ``connect_url`` and timeout).
        auth_header: ``Authorization`` header value (bearer token or JWT).
        payload: JSON body to send.
        max_retries: Maximum number of attempts before giving up.

    Returns:
        The parsed JSON response body.

    Raises:
        SelfServiceError: On non-retryable client errors or after all
            retry attempts are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=settings.self_service_timeout_sec
            ) as client:
                headers = {
                    "Authorization": auth_header,
                    **settings.self_service_connect_headers,
                }
                response = await client.post(
                    settings.connect_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise SelfServiceError(
                    f"Self-service request failed ({exc.response.status_code}): "
                    f"{exc.response.text[:400]}"
                ) from exc
            last_exc = exc
        except httpx.TransportError as exc:
            last_exc = exc

        if attempt < max_retries:
            delay = 1.0 * (2.0 ** (attempt - 1))
            logger.warning(
                "Connect request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                settings.connect_url,
                attempt,
                max_retries,
                last_exc,
                delay,
            )
            await asyncio.sleep(delay)

    raise SelfServiceError(
        f"Self-service connect failed after {max_retries} attempts: {last_exc}"
    ) from last_exc


async def fetch_self_service_bundle(settings: Settings) -> dict[str, Any]:
    """Fetch the provisioning bundle using a one-time self-service token.

    POSTs the machine fingerprint to the Coda connect endpoint.  The
    returned bundle contains JWT keys, Redis URL, API paths, and
    optional VPN configuration.

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
    }
    return await _post_connect(
        settings,
        auth_header=f"Bearer {settings.self_service_token}",
        payload=payload,
        max_retries=settings.self_service_connect_retries,
    )


async def fetch_reconnect_bundle(settings: Settings) -> dict[str, Any]:
    """Fetch a reconnect bundle using stored JWT credentials.

    Authenticates with a freshly signed JWT (instead of a self-service
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
        max_retries=settings.self_service_connect_retries,
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
            from self_service.vpn.guard import detect_tun_interface

            iface = await asyncio.to_thread(
                detect_tun_interface, settings.vpn_interface_hint
            )
            if iface is None:
                await asyncio.to_thread(
                    _start_openvpn, settings.self_service_vpn_profile_path
                )
                await _wait_for_tunnel(hint=settings.vpn_interface_hint)


async def connect_settings(settings: Settings) -> None:
    """Provision or reconnect the node to the Coda cloud.

    On first run (token present), fetches a self-service bundle.  On
    subsequent runs (no token), restores the persisted VPN tunnel and
    fetches a reconnect bundle with stored JWT credentials.

    After the bundle is applied and config is persisted, any failure
    triggers cleanup of a potentially half-started VPN daemon.

    Args:
        settings: Runtime settings to populate.

    Raises:
        SelfServiceError: On provisioning or reconnect failure.
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
                "Persisted VPN profile not found. Re-run self-service provisioning with a new token."
            )
        return

    from self_service.vpn.guard import detect_tun_interface

    iface = await asyncio.to_thread(detect_tun_interface, settings.vpn_interface_hint)
    if iface is not None:
        return

    await asyncio.to_thread(_start_openvpn, settings.self_service_vpn_profile_path)
    await _wait_for_tunnel(hint=settings.vpn_interface_hint)
