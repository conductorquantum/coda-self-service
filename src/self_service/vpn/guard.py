"""VPN preflight checks and ongoing health monitoring.

The :class:`VPNGuard` runs a three-stage preflight (interface detection,
DNS resolution, HTTP probes) and then enters a background watch loop
that continuously re-evaluates VPN health, firing a callback whenever
the service state changes.

Platform-specific helpers detect active tunnel interfaces on macOS
(``ifconfig``), Linux (``ip link``), and Windows (``Get-NetAdapter``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "ProbeResult",
    "ServiceState",
    "VPNGuard",
    "VPNStatus",
    "detect_tun_interface",
    "validate_key_permissions",
]


class ServiceState(Enum):
    """Overall readiness state of the node runtime."""

    BOOTING = "booting"
    VPN_UNAVAILABLE = "vpn_unavailable"
    READY = "ready"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single HTTP health probe against a VPN endpoint."""

    target: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class VPNStatus:
    """Aggregate result of a VPN preflight or health check."""

    ok: bool
    interface_found: bool
    probes: list[ProbeResult] = field(default_factory=list)
    reason: str = ""


def _parse_darwin_tun_interfaces(ifconfig_output: str) -> str | None:
    """Extract the first active utun/tun interface from ``ifconfig`` output."""
    current_iface: str | None = None
    for line in ifconfig_output.splitlines():
        if line and not line[0].isspace():
            current_iface = line.split(":")[0]
        elif (
            current_iface
            and current_iface.startswith(("utun", "tun"))
            and line.strip().startswith("inet ")
        ):
            return current_iface
    return None


def _parse_windows_tun_interfaces(
    adapter_json: str, hint: str | None = None
) -> str | None:
    """Find a TAP/WinTUN adapter from ``Get-NetAdapter`` JSON output."""
    try:
        raw_adapters = json.loads(adapter_json)
    except json.JSONDecodeError:
        return None

    if isinstance(raw_adapters, dict):
        adapters = [raw_adapters]
    elif isinstance(raw_adapters, list):
        adapters = raw_adapters
    else:
        return None

    hint_lower = hint.lower() if hint else None
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue

        name = adapter.get("Name")
        description = adapter.get("InterfaceDescription")
        status = adapter.get("Status")
        if not isinstance(name, str) or not isinstance(description, str):
            continue
        if not isinstance(status, str) or status.lower() != "up":
            continue
        if (
            hint_lower
            and hint_lower not in name.lower()
            and hint_lower not in description.lower()
        ):
            continue

        description_lower = description.lower()
        if any(
            marker in description_lower
            for marker in ("tap-windows", "wintun", "openvpn", "tap adapter")
        ):
            return name
    return None


def detect_tun_interface(hint: str | None = None) -> str | None:
    """Detect an active VPN tunnel interface on the local machine.

    Uses platform-specific commands (``ifconfig`` on macOS, ``ip link``
    on Linux, ``Get-NetAdapter`` on Windows) to find a TUN/TAP adapter
    that is currently UP.

    Args:
        hint: If provided, check only this specific interface name
            instead of scanning all interfaces.

    Returns:
        The interface name (e.g. ``"utun3"``, ``"tun0"``) or ``None``
        if no active VPN interface is found.
    """
    system = platform.system()

    if hint:
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["ifconfig", hint],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            elif system == "Windows":
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        (
                            "Get-NetAdapter -IncludeHidden | "
                            "Select-Object Name,InterfaceDescription,Status | "
                            "ConvertTo-Json -Compress"
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            else:
                result = subprocess.run(
                    ["ip", "link", "show", hint],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

            if system == "Windows":
                return _parse_windows_tun_interfaces(result.stdout, hint)
            if result.returncode == 0 and (
                "UP" in result.stdout or "up" in result.stdout
            ):
                return hint
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        return None

    try:
        if system == "Darwin":
            result = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return _parse_darwin_tun_interfaces(result.stdout)

        if system == "Windows":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-NetAdapter -IncludeHidden | "
                        "Select-Object Name,InterfaceDescription,Status | "
                        "ConvertTo-Json -Compress"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return _parse_windows_tun_interfaces(result.stdout)

        result = subprocess.run(
            ["ip", "-o", "link", "show", "type", "tun"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                return parts[1].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    return None


async def _probe_target(url: str, timeout: float = 5.0) -> ProbeResult:
    """Send an HTTP HEAD to *url* and return a :class:`ProbeResult`."""
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
            response = await client.head(url)
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            return ProbeResult(
                target=url,
                ok=response.status_code < 500,
                latency_ms=latency_ms,
            )
    except Exception as exc:
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        return ProbeResult(
            target=url,
            ok=False,
            latency_ms=latency_ms,
            error=str(exc)[:200],
        )


def _resolve_host(hostname: str) -> bool:
    """Return ``True`` if *hostname* resolves to at least one address."""
    try:
        socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return True
    except (OSError, socket.gaierror):
        return False


class VPNGuard:
    """Monitor VPN health and expose readiness state.

    The guard starts in :attr:`ServiceState.BOOTING` and transitions to
    READY, VPN_UNAVAILABLE, or DEGRADED based on the preflight and
    ongoing watch results.

    Args:
        probe_targets: HTTP URLs to probe for connectivity (typically
            the Coda API endpoints reachable only over VPN).
        interface_hint: Specific interface name to look for instead of
            auto-detecting.
        check_interval_sec: Seconds between background health checks.
        vpn_required: When ``False``, preflight passes even without a
            detected tunnel (useful for local development).
    """

    def __init__(
        self,
        probe_targets: list[str] | None = None,
        interface_hint: str | None = None,
        check_interval_sec: int = 10,
        vpn_required: bool = True,
    ) -> None:
        self._probe_targets = probe_targets or []
        self._interface_hint = interface_hint
        self._check_interval = check_interval_sec
        self._vpn_required = vpn_required
        self._state = ServiceState.BOOTING
        self._running = False

    @property
    def state(self) -> ServiceState:
        """Current service state of the VPN guard."""
        return self._state

    @property
    def is_ready(self) -> bool:
        """``True`` when the VPN guard considers the node fully healthy."""
        return self._state == ServiceState.READY

    async def preflight(self) -> VPNStatus:
        """Run a full VPN health check: interface, DNS, and HTTP probes.

        Updates :attr:`state` and returns a :class:`VPNStatus` summary.
        When *vpn_required* is ``False``, all checks pass regardless of
        the actual tunnel state.
        """
        iface = await asyncio.to_thread(detect_tun_interface, self._interface_hint)
        interface_found = iface is not None

        if not interface_found and self._vpn_required:
            self._state = ServiceState.VPN_UNAVAILABLE
            return VPNStatus(
                ok=False,
                interface_found=False,
                reason="No VPN tunnel interface detected",
            )

        dns_failures: list[str] = []
        for target in self._probe_targets:
            hostname = urlparse(target).hostname
            if hostname and not await asyncio.to_thread(_resolve_host, hostname):
                dns_failures.append(hostname)

        if dns_failures and self._vpn_required:
            self._state = ServiceState.VPN_UNAVAILABLE
            return VPNStatus(
                ok=False,
                interface_found=interface_found,
                reason=f"DNS resolution failed for: {', '.join(dns_failures)}",
            )

        probes: list[ProbeResult] = []
        for target in self._probe_targets:
            probes.append(await _probe_target(target))

        failed = [probe for probe in probes if not probe.ok]
        if failed and self._vpn_required:
            self._state = ServiceState.VPN_UNAVAILABLE
            reasons = "; ".join(
                f"{probe.target}: {probe.error or 'unreachable'}" for probe in failed
            )
            return VPNStatus(
                ok=False,
                interface_found=interface_found,
                probes=probes,
                reason=f"Probe failures: {reasons}",
            )

        self._state = ServiceState.READY
        return VPNStatus(ok=True, interface_found=interface_found, probes=probes)

    async def watch(
        self,
        on_change: Callable[[ServiceState], Awaitable[None]] | None = None,
    ) -> None:
        """Continuously monitor VPN health until :meth:`stop` is called.

        Runs :meth:`preflight` every *check_interval_sec* seconds and
        invokes *on_change* whenever the service transitions between
        READY and DEGRADED.

        Args:
            on_change: Optional async callback invoked with the new
                :class:`ServiceState` on each transition.
        """
        self._running = True
        while self._running:
            await asyncio.sleep(self._check_interval)
            previous = self._state
            status = await self.preflight()

            if status.ok and previous not in (ServiceState.READY, ServiceState.BOOTING):
                if on_change:
                    await on_change(ServiceState.READY)
            elif not status.ok and previous == ServiceState.READY:
                self._state = ServiceState.DEGRADED
                if on_change:
                    await on_change(ServiceState.DEGRADED)

    def stop(self) -> None:
        """Signal the watch loop to exit after the current iteration."""
        self._running = False


def validate_key_permissions(path: str) -> bool:
    """Check that a key file has restrictive permissions.

    On POSIX systems the file must be mode ``0600`` or ``0400``.  On
    Windows the check only verifies the file exists (NTFS ACLs are not
    inspected).

    Args:
        path: Filesystem path to the key file.

    Returns:
        ``True`` if the file exists and has acceptable permissions.
    """
    try:
        p = Path(path)
        if platform.system() == "Windows":
            return p.is_file()
        mode = p.stat().st_mode & 0o777
        return mode in (0o600, 0o400)
    except OSError:
        return False
