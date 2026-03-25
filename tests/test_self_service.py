"""Tests for self-service provisioning and VPN tunnel setup."""

import json
import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from self_service.server.config import Settings
from self_service.vpn.service import (
    SelfServiceError,
    _post_connect,
    _start_openvpn,
    _validate_vpn_profile,
    _wait_for_tunnel,
    apply_self_service_bundle,
    connect_settings,
    ensure_persisted_vpn,
    fetch_reconnect_bundle,
    fetch_self_service_bundle,
    kill_openvpn_daemon,
    self_service_settings,
)


@pytest.fixture(autouse=True)
def self_service_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-self-service-token")


def _sample_bundle() -> dict[str, object]:
    return {
        "qpu_id": "cq-node-test",
        "qpu_display_name": "Test Node",
        "native_gate_set": "cz",
        "num_qubits": 7,
        "jwt_private_key": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        "jwt_key_id": "cq-node-test-key-001",
        "redis_url": "rediss://default:token@host:6379",
        "cloud_base_url": "https://coda.conductorquantum.com",
        "connect_path": "/api/internal/qpu/connect",
        "register_path": "/api/internal/qpu/register",
        "heartbeat_path": "/api/internal/qpu/heartbeat",
        "webhook_path": "/api/internal/qpu/webhook",
        "stream_key": "qpu:cq-node-test:jobs",
        "webhook_url": "https://coda.conductorquantum.com/api/internal/qpu/webhook",
        "connect_id": "connect-123",
        "vpn": {
            "required": True,
            "interface_hint": "utun5",
            "check_interval_sec": 12,
            "probe_targets": [
                "https://coda.conductorquantum.com/api/internal/qpu/register"
            ],
            "client_profile_ovpn": None,
        },
    }


class TestFetchSelfServiceBundle:
    @pytest.mark.asyncio
    async def test_requires_token(self) -> None:
        settings = Settings()
        settings.jwt_private_key = "placeholder"
        settings.jwt_key_id = "placeholder"
        settings.self_service_token = ""
        with pytest.raises(SelfServiceError, match="self-service token is empty"):
            await fetch_self_service_bundle(settings)

    @pytest.mark.asyncio
    async def test_fetches_bundle(self) -> None:
        settings = Settings()
        settings.self_service_token = "self-service-token"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _sample_bundle()

        with patch("self_service.vpn.service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = client

            bundle = await fetch_self_service_bundle(settings)

        assert bundle["qpu_id"] == "cq-node-test"
        request_body = client.post.call_args.kwargs["json"]
        assert "qpu_id" not in request_body
        assert set(request_body) == {"machine_fingerprint"}
        assert request_body["machine_fingerprint"]
        assert client.post.call_args.args[0] == settings.connect_url

    @pytest.mark.asyncio
    async def test_fetches_reconnect_bundle_with_jwt(self) -> None:
        settings = Settings()
        settings.jwt_private_key = "private-key"
        settings.jwt_key_id = "kid-123"
        settings.self_service_token = ""
        settings.qpu_id = "cq-node-test"
        settings.self_service_machine_fingerprint = "fingerprint-123"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _sample_bundle()

        with (
            patch(
                "self_service.vpn.service.sign_token", return_value="signed-jwt"
            ) as mock_sign,
            patch("self_service.vpn.service.httpx.AsyncClient") as mock_client_cls,
        ):
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = client

            bundle = await fetch_reconnect_bundle(settings)

        assert bundle["qpu_id"] == "cq-node-test"
        mock_sign.assert_called_once_with(
            "cq-node-test",
            "private-key",
            key_id="kid-123",
        )
        assert (
            client.post.call_args.kwargs["headers"]["Authorization"]
            == "Bearer signed-jwt"
        )
        assert (
            client.post.call_args.kwargs["json"]["machine_fingerprint"]
            == "fingerprint-123"
        )
        assert set(client.post.call_args.kwargs["json"]) == {"machine_fingerprint"}


class TestPostConnectRetry:
    @pytest.mark.asyncio
    async def test_retries_on_5xx_then_succeeds(self) -> None:
        settings = Settings()
        settings.self_service_token = "tok"
        settings.webapp_url = "https://example.com"

        error_response = MagicMock()
        error_response.status_code = 503
        error_response.text = "Service Unavailable"
        error_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "503", request=MagicMock(), response=error_response
            )
        )

        ok_response = MagicMock()
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {"ok": True}

        with patch("self_service.vpn.service.httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.post = AsyncMock(side_effect=[error_response, ok_response])
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = client

            with patch(
                "self_service.vpn.service.asyncio.sleep", new_callable=AsyncMock
            ):
                result = await _post_connect(
                    settings,
                    auth_header="Bearer tok",
                    payload={},
                    max_retries=3,
                )

        assert result == {"ok": True}
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self) -> None:
        settings = Settings()
        settings.self_service_token = "tok"
        settings.webapp_url = "https://example.com"

        error_response = MagicMock()
        error_response.status_code = 401
        error_response.text = "Unauthorized"
        error_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=error_response
            )
        )

        with patch("self_service.vpn.service.httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.post = AsyncMock(return_value=error_response)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = client

            with pytest.raises(SelfServiceError, match="401"):
                await _post_connect(
                    settings,
                    auth_header="Bearer tok",
                    payload={},
                    max_retries=3,
                )

        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_after_retries_exhausted(self) -> None:
        settings = Settings()
        settings.self_service_token = "tok"
        settings.webapp_url = "https://example.com"

        error_response = MagicMock()
        error_response.status_code = 502
        error_response.text = "Bad Gateway"
        error_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "502", request=MagicMock(), response=error_response
            )
        )

        with patch("self_service.vpn.service.httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.post = AsyncMock(return_value=error_response)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = client

            with (
                patch("self_service.vpn.service.asyncio.sleep", new_callable=AsyncMock),
                pytest.raises(SelfServiceError, match="after 2 attempts"),
            ):
                await _post_connect(
                    settings,
                    auth_header="Bearer tok",
                    payload={},
                    max_retries=2,
                )

        assert client.post.call_count == 2


class TestApplySelfServiceBundle:
    @pytest.mark.asyncio
    async def test_applies_bundle_fields(self) -> None:
        settings = Settings()
        settings.self_service_auto_vpn = False
        bundle = _sample_bundle()
        vpn = cast(dict[str, Any], bundle["vpn"])
        vpn["required"] = False

        await apply_self_service_bundle(settings, bundle)

        assert settings.qpu_id == "cq-node-test"
        assert settings.jwt_key_id == "cq-node-test-key-001"
        assert settings.redis_url.startswith("rediss://")
        assert settings.vpn_interface_hint == "utun5"
        assert settings.connect_path == "/api/internal/qpu/connect"

    @pytest.mark.asyncio
    async def test_accepts_qpu_label_field(self) -> None:
        settings = Settings()
        settings.self_service_auto_vpn = False
        bundle = _sample_bundle()
        bundle.pop("qpu_display_name")
        bundle["qpu_label"] = "Label Node"
        vpn = cast(dict[str, Any], bundle["vpn"])
        vpn["required"] = False

        await apply_self_service_bundle(settings, bundle)

        assert settings.qpu_display_name == "Label Node"

    @pytest.mark.asyncio
    async def test_reconnect_bundle_keeps_existing_private_key(self) -> None:
        settings = Settings()
        settings.self_service_auto_vpn = False
        settings.jwt_private_key = "persisted-private-key"
        settings.jwt_key_id = "persisted-key-id"
        settings.self_service_token = ""
        bundle = _sample_bundle()
        bundle.pop("jwt_private_key", None)
        vpn = cast(dict[str, Any], bundle["vpn"])
        vpn["required"] = False

        await apply_self_service_bundle(settings, bundle)

        assert settings.jwt_private_key == "persisted-private-key"
        assert settings.jwt_key_id == "cq-node-test-key-001"

    @pytest.mark.asyncio
    async def test_requires_profile_when_vpn_required(self) -> None:
        settings = Settings()
        settings.self_service_auto_vpn = False
        with pytest.raises(SelfServiceError, match="VPN is required"):
            await apply_self_service_bundle(settings, _sample_bundle())


class TestWaitForTunnel:
    @pytest.mark.asyncio
    async def test_returns_interface_immediately(self) -> None:
        with patch("self_service.vpn.guard.detect_tun_interface", return_value="utun5"):
            assert await _wait_for_tunnel(hint="utun5", timeout=1.0) == "utun5"

    @pytest.mark.asyncio
    async def test_kills_daemon_on_timeout(self) -> None:
        with (
            patch("self_service.vpn.guard.detect_tun_interface", return_value=None),
            patch("self_service.vpn.service._read_openvpn_log_tail", return_value=""),
            patch("self_service.vpn.service.kill_openvpn_daemon") as mock_kill,
        ):
            with pytest.raises(SelfServiceError):
                await _wait_for_tunnel(timeout=0.1, poll_interval=0.05)
            mock_kill.assert_called_once()


class TestValidateVpnProfile:
    def test_accepts_clean_profile(self) -> None:
        _validate_vpn_profile(
            "client\nremote vpn.example.com 1194\ndev tun\nproto udp\n"
        )

    def test_rejects_dangerous_directive(self) -> None:
        with pytest.raises(SelfServiceError, match="forbidden directive"):
            _validate_vpn_profile(
                "client\nremote vpn.example.com 1194\nup /bin/malicious\n"
            )


class TestStartOpenvpn:
    @patch("self_service.vpn.service.os.name", "nt")
    @patch("self_service.vpn.service._openvpn_binary", return_value="openvpn.exe")
    @patch("self_service.vpn.service.subprocess.Popen")
    def test_windows_launch_writes_pid_file(
        self,
        mock_popen: MagicMock,
        _binary: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid_path = tmp_path / "coda.pid"
        log_path = tmp_path / "coda.log"
        monkeypatch.setattr("self_service.vpn.service.OPENVPN_PID_PATH", pid_path)
        monkeypatch.setattr("self_service.vpn.service.OPENVPN_LOG_PATH", log_path)
        mock_popen.return_value = MagicMock(pid=4321)

        _start_openvpn("C:\\vpn\\client.ovpn")

        assert pid_path.read_text().strip() == "4321"


class TestKillOpenvpnDaemon:
    def test_returns_false_when_no_pid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "self_service.vpn.service.OPENVPN_PID_PATH",
            tmp_path / "missing.pid",
        )
        assert kill_openvpn_daemon() is False

    @patch("self_service.vpn.service.os.name", "nt")
    @patch("self_service.vpn.service.subprocess.run")
    def test_windows_uses_taskkill(
        self, mock_run: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid_file = tmp_path / "coda.pid"
        pid_file.write_text("1234")
        monkeypatch.setattr("self_service.vpn.service.OPENVPN_PID_PATH", pid_file)

        assert kill_openvpn_daemon() is True
        mock_run.assert_called_once()
        assert not pid_file.exists()


class TestSelfServiceSettings:
    @pytest.mark.asyncio
    async def test_cleanup_on_apply_failure(self) -> None:
        settings = Settings()
        settings.self_service_token = "tok"
        with (
            patch(
                "self_service.vpn.service.fetch_self_service_bundle",
                new_callable=AsyncMock,
                return_value={"qpu_id": "a"},
            ),
            patch(
                "self_service.vpn.service.apply_self_service_bundle",
                new_callable=AsyncMock,
                side_effect=SelfServiceError("bad bundle"),
            ),
            patch("self_service.vpn.service.kill_openvpn_daemon") as mock_kill,
        ):
            with pytest.raises(SelfServiceError, match="bad bundle"):
                await self_service_settings(settings)
            mock_kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_persists_runtime_config_after_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings()
        settings.self_service_token = "tok"
        settings.self_service_auto_vpn = False
        bundle = _sample_bundle()
        vpn = cast(dict[str, Any], bundle["vpn"])
        vpn["required"] = False

        config_path = tmp_path / "coda.config"
        key_path = tmp_path / "coda-private-key"
        monkeypatch.setattr(
            "self_service.vpn.service.PERSISTED_CONFIG_PATH", config_path
        )
        monkeypatch.setattr(
            "self_service.vpn.service.PERSISTED_PRIVATE_KEY_PATH", key_path
        )

        with patch(
            "self_service.vpn.service.fetch_self_service_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            await self_service_settings(settings)

        assert key_path.read_text() == bundle["jwt_private_key"]
        persisted = json.loads(config_path.read_text())
        assert persisted["qpu_id"] == "cq-node-test"
        assert persisted["jwt_private_key_path"] == str(key_path)
        assert persisted["connect_path"] == "/api/internal/qpu/connect"
        assert persisted["self_service_machine_fingerprint"]
        assert "advertised_provider" not in persisted
        if os.name != "nt":
            assert config_path.stat().st_mode & 0o777 == 0o600
            assert key_path.stat().st_mode & 0o777 == 0o600

    @pytest.mark.asyncio
    async def test_connect_settings_reuses_persisted_vpn_for_reconnect(self) -> None:
        settings = Settings()
        settings.jwt_private_key = "persisted-private-key"
        settings.jwt_key_id = "persisted-key-id"
        settings.self_service_token = ""
        settings.qpu_id = "cq-node-test"
        settings.self_service_auto_vpn = False
        bundle = _sample_bundle()
        bundle.pop("jwt_private_key", None)
        vpn = cast(dict[str, Any], bundle["vpn"])
        vpn["required"] = False

        with (
            patch(
                "self_service.vpn.service.ensure_persisted_vpn",
                new_callable=AsyncMock,
            ) as mock_ensure_vpn,
            patch(
                "self_service.vpn.service.fetch_reconnect_bundle",
                new_callable=AsyncMock,
                return_value=bundle,
            ) as mock_fetch,
        ):
            await connect_settings(settings)

        mock_ensure_vpn.assert_awaited_once_with(settings)
        mock_fetch.assert_awaited_once_with(settings)


class TestReconnectWorkflow:
    @pytest.mark.asyncio
    async def test_ensure_persisted_vpn_starts_openvpn_when_profile_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "coda.config"
        config_path.write_text("{}\n")
        if os.name != "nt":
            config_path.chmod(0o600)
        profile_path = tmp_path / "coda-self-service.ovpn"
        profile_path.write_text("client\nremote vpn.example.com 443\n")

        monkeypatch.setattr(
            "self_service.vpn.service.PERSISTED_CONFIG_PATH", config_path
        )

        settings = Settings()
        settings.jwt_private_key = "placeholder"
        settings.jwt_key_id = "placeholder"
        settings.self_service_token = ""
        settings.self_service_auto_vpn = True
        settings.vpn_required = True
        settings.self_service_vpn_profile_path = str(profile_path)
        settings.vpn_interface_hint = "utun5"

        with (
            patch("self_service.vpn.guard.detect_tun_interface", return_value=None),
            patch("self_service.vpn.service._start_openvpn") as mock_start,
            patch(
                "self_service.vpn.service._wait_for_tunnel", new_callable=AsyncMock
            ) as mock_wait,
        ):
            await ensure_persisted_vpn(settings)

        mock_start.assert_called_once_with(str(profile_path))
        mock_wait.assert_awaited_once_with(hint="utun5")
