"""Tests for environment-backed settings."""

import json
import os
from pathlib import Path

import pytest

from self_service.server import config as config_module
from self_service.server.config import Settings


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CODA_JWT_PRIVATE_KEY",
        "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
    )
    monkeypatch.setenv("CODA_JWT_KEY_ID", "test-key-id")


class TestSettings:
    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.qpu_id == ""
        assert settings.qpu_display_name == ""
        assert settings.port == 8080
        assert settings.self_service_token == ""
        assert settings.self_service_auto_vpn is True
        assert settings.advertised_provider == "coda"
        assert settings.connect_path == "/api/internal/qpu/connect"
        assert settings.webapp_url == "https://coda.conductorquantum.com"

    def test_callback_urls(self) -> None:
        settings = Settings()
        assert (
            settings.callback_url == f"{settings.webapp_url}/api/internal/qpu/webhook"
        )
        assert settings.connect_url == f"{settings.webapp_url}/api/internal/qpu/connect"
        assert settings.vpn_probe_urls == [
            f"{settings.webapp_url}/api/internal/qpu/health",
        ]
        assert (
            settings.heartbeat_url
            == f"{settings.webapp_url}/api/internal/qpu/heartbeat"
        )

    def test_vpn_probe_urls_empty_when_vpn_not_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_VPN_REQUIRED", "false")
        settings = Settings()
        assert settings.vpn_probe_urls == []

    def test_vpn_probe_urls_uses_explicit_targets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_VPN_PROBE_TARGETS", '["https://example.test/health"]')
        settings = Settings()
        assert settings.vpn_probe_urls == ["https://example.test/health"]

    def test_custom_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODA_QPU_ID", "custom-node")
        monkeypatch.setenv("CODA_PORT", "9090")
        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "token")
        monkeypatch.setenv("CODA_WEBAPP_URL", "https://example.test")
        monkeypatch.setenv("CODA_EXECUTOR_FACTORY", "pkg.module:create_executor")
        settings = Settings()
        assert settings.qpu_id == "custom-node"
        assert settings.port == 9090
        assert settings.self_service_token == "token"
        assert settings.webapp_url == "https://example.test"
        assert settings.executor_factory == "pkg.module:create_executor"

    def test_empty_jwt_without_self_service_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_JWT_PRIVATE_KEY", "")
        monkeypatch.setenv("CODA_JWT_KEY_ID", "")
        monkeypatch.delenv("CODA_SELF_SERVICE_TOKEN", raising=False)
        with pytest.raises(Exception, match="CODA_JWT_PRIVATE_KEY must be set"):
            Settings()

    def test_empty_jwt_with_self_service_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_JWT_PRIVATE_KEY", "")
        monkeypatch.setenv("CODA_JWT_KEY_ID", "")
        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "self-service-token")
        settings = Settings()
        assert settings.self_service_token == "self-service-token"

    def test_loads_persisted_runtime_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "coda.config"
        key_path = tmp_path / "coda-private-key"
        key_path.write_text(
            "-----BEGIN PRIVATE KEY-----\npersisted\n-----END PRIVATE KEY-----\n"
        )
        if os.name != "nt":
            key_path.chmod(0o600)
        config_path.write_text(
            json.dumps(
                {
                    "qpu_id": "persisted-node",
                    "qpu_display_name": "Persisted Node",
                    "native_gate_set": "cz",
                    "num_qubits": 9,
                    "jwt_key_id": "persisted-key-id",
                    "jwt_private_key_path": str(key_path),
                    "redis_url": "rediss://default:token@persisted:6379",
                    "webapp_url": "https://persisted.example.test",
                    "connect_path": "/api/internal/qpu/connect",
                    "heartbeat_path": "/api/internal/qpu/heartbeat",
                    "webhook_path": "/api/internal/qpu/webhook",
                    "vpn_required": True,
                    "vpn_check_interval_sec": 15,
                    "vpn_probe_targets": [
                        "https://persisted.example.test/api/internal/qpu/health"
                    ],
                    "advertised_provider": "legacy-provider",
                    "self_service_machine_fingerprint": "persisted-fingerprint",
                }
            )
            + "\n"
        )
        if os.name != "nt":
            config_path.chmod(0o600)

        monkeypatch.setattr(config_module, "PERSISTED_CONFIG_PATH", config_path)
        monkeypatch.setattr(config_module, "PERSISTED_PRIVATE_KEY_PATH", key_path)
        monkeypatch.setenv("CODA_JWT_PRIVATE_KEY", "")
        monkeypatch.setenv("CODA_JWT_KEY_ID", "")
        monkeypatch.delenv("CODA_SELF_SERVICE_TOKEN", raising=False)

        settings = Settings()

        assert settings.qpu_id == "persisted-node"
        assert settings.qpu_display_name == "Persisted Node"
        assert settings.jwt_key_id == "persisted-key-id"
        assert settings.jwt_private_key.startswith("-----BEGIN PRIVATE KEY-----")
        assert settings.redis_url == "rediss://default:token@persisted:6379"
        assert settings.connect_path == "/api/internal/qpu/connect"
        assert settings.self_service_machine_fingerprint == "persisted-fingerprint"
        assert settings.advertised_provider == "coda"
        assert settings.vpn_probe_targets == [
            "https://persisted.example.test/api/internal/qpu/health"
        ]


class TestDefaultDeviceConfig:
    def test_default_device_config_when_file_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        device_yaml = site_dir / "device.yaml"
        device_yaml.write_text("target: test\n")

        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.device_config == "site/device.yaml"

    def test_no_default_device_config_when_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.device_config == ""

    def test_explicit_device_config_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "device.yaml").write_text("target: test\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CODA_DEVICE_CONFIG", "/explicit/path.yaml")
        settings = Settings()
        assert settings.device_config == "/explicit/path.yaml"
