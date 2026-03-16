"""Tests for VPN detection and monitoring."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from self_service.vpn import ServiceState, VPNGuard, VPNStatus, validate_key_permissions
from self_service.vpn.guard import (
    _parse_darwin_tun_interfaces,
    _parse_windows_tun_interfaces,
    _probe_target,
    _resolve_host,
    detect_tun_interface,
)


def test_parse_darwin_tun_interfaces() -> None:
    output = (
        "utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
        "\tinet6 fe80::1%utun0 prefixlen 64 scopeid 0x1\n"
        "utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1500\n"
        "\tinet 10.0.0.2 --> 10.0.0.1 netmask 0xffffff00\n"
    )
    assert _parse_darwin_tun_interfaces(output) == "utun3"


def test_parse_windows_tun_interfaces() -> None:
    output = (
        '[{"Name":"Ethernet","InterfaceDescription":"Intel Ethernet","Status":"Up"},'
        '{"Name":"OpenVPN Wintun","InterfaceDescription":"OpenVPN Wintun","Status":"Up"}]'
    )
    assert _parse_windows_tun_interfaces(output) == "OpenVPN Wintun"


@patch("self_service.vpn.guard.subprocess.run")
@patch("self_service.vpn.guard.platform.system", return_value="Windows")
def test_detect_tun_interface_windows(_sys: MagicMock, mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='[{"Name":"OpenVPN Wintun","InterfaceDescription":"OpenVPN Wintun","Status":"Up"}]',
    )
    assert detect_tun_interface() == "OpenVPN Wintun"


@patch("self_service.vpn.guard.socket.getaddrinfo")
def test_resolve_host(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("1.2.3.4", 443))]
    assert _resolve_host("example.com") is True


@pytest.mark.asyncio
async def test_probe_target_success() -> None:
    mock_response = MagicMock(status_code=200)
    with patch("self_service.vpn.guard.httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.head = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = instance

        result = await _probe_target("https://example.com/health")

    assert result.ok is True
    assert result.error is None


@pytest.mark.asyncio
async def test_probe_target_connection_error() -> None:
    with patch("self_service.vpn.guard.httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.head = AsyncMock(side_effect=httpx.ConnectError("refused"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = instance

        result = await _probe_target("https://dead.host/health")

    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_vpn_guard_passes_when_not_required() -> None:
    with patch("self_service.vpn.guard.detect_tun_interface", return_value=None):
        guard = VPNGuard(vpn_required=False)
        status = await guard.preflight()
    assert status.ok is True
    assert guard.state == ServiceState.READY


@pytest.mark.asyncio
async def test_vpn_guard_detects_recovery() -> None:
    call_count = 0
    states: list[ServiceState] = []

    async def on_change(state: ServiceState) -> None:
        states.append(state)

    guard = VPNGuard(check_interval_sec=0, vpn_required=True)
    guard._state = ServiceState.READY
    results = [
        VPNStatus(ok=False, interface_found=False, reason="down"),
        VPNStatus(ok=True, interface_found=True),
    ]

    async def fake_preflight() -> VPNStatus:
        nonlocal call_count
        result = results[min(call_count, len(results) - 1)]
        call_count += 1
        guard._state = ServiceState.READY if result.ok else ServiceState.VPN_UNAVAILABLE
        if call_count >= len(results) + 1:
            guard.stop()
        return result

    guard.preflight = fake_preflight  # type: ignore[method-assign]
    await guard.watch(on_change=on_change)
    assert ServiceState.DEGRADED in states
    assert ServiceState.READY in states


def test_validate_key_permissions(tmp_path: Path) -> None:
    key_file = tmp_path / "test.key"
    key_file.write_text("private-key-data")
    key_file.chmod(0o600)
    assert validate_key_permissions(str(key_file)) is True


@patch("self_service.vpn.guard.platform.system", return_value="Windows")
def test_validate_key_permissions_windows(_sys: MagicMock, tmp_path: Path) -> None:
    key_file = tmp_path / "test.key"
    key_file.write_text("private-key-data")
    assert validate_key_permissions(str(key_file)) is True
