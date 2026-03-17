"""Tests for the framework subsystem: DeviceConfig, Registry, QUA and QubiC stubs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from self_service.errors import ConfigError, ExecutorError
from self_service.frameworks.base import DeviceConfig, Framework
from self_service.frameworks.qua import QUAFramework
from self_service.frameworks.qubic import QubiCFramework
from self_service.frameworks.registry import FrameworkRegistry, default_registry
from self_service.server.executor import NoopExecutor, load_executor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubFramework:
    """Minimal Framework implementation for testing."""

    def __init__(self, name: str, targets: frozenset[str]) -> None:
        self._name = name
        self._targets = targets

    @property
    def name(self) -> str:
        return self._name

    @property
    def supported_targets(self) -> frozenset[str]:
        return self._targets

    def validate_config(self, device_config: DeviceConfig) -> list[str]:
        return []

    def create_executor(self, device_config: DeviceConfig, settings: Any) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# DeviceConfig
# ---------------------------------------------------------------------------


class TestDeviceConfig:
    def test_construction(self) -> None:
        config = DeviceConfig(target="superconducting_cz", num_qubits=3)
        assert config.target == "superconducting_cz"
        assert config.num_qubits == 3
        assert config.framework == ""
        assert config.calibration_path == ""

    def test_extra_fields_preserved(self) -> None:
        config = DeviceConfig(
            target="superconducting_cz",
            num_qubits=3,
            opx_host="192.168.1.100",
            opx_port=80,
        )
        assert config.get_option("opx_host") == "192.168.1.100"
        assert config.get_option("opx_port") == 80
        assert config.get_options() == {"opx_host": "192.168.1.100", "opx_port": 80}

    def test_get_option_default(self) -> None:
        config = DeviceConfig(target="superconducting_cz", num_qubits=1)
        assert config.get_option("missing") is None
        assert config.get_option("missing", "fallback") == "fallback"

    def test_empty_target_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DeviceConfig(target="", num_qubits=1)

    def test_num_qubits_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            DeviceConfig(target="x", num_qubits=0)

    def test_num_qubits_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            DeviceConfig(target="x", num_qubits=51)

    def test_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "device.yaml"
        yaml_file.write_text(
            "framework: qua\n"
            "target: superconducting_cz\n"
            "num_qubits: 3\n"
            "calibration_path: cal.yaml\n"
            "opx_host: 10.0.0.1\n"
        )
        config = DeviceConfig.from_yaml(yaml_file)
        assert config.framework == "qua"
        assert config.target == "superconducting_cz"
        assert config.num_qubits == 3
        assert config.calibration_path == "cal.yaml"
        assert config.get_option("opx_host") == "10.0.0.1"

    def test_from_yaml_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            DeviceConfig.from_yaml("/nonexistent/device.yaml")

    def test_from_yaml_non_mapping(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("- a\n- b\n")
        with pytest.raises(ValueError, match="expected a YAML mapping"):
            DeviceConfig.from_yaml(yaml_file)

    def test_resolved_calibration_path_empty(self) -> None:
        config = DeviceConfig(target="x", num_qubits=1)
        assert config.resolved_calibration_path is None

    def test_resolved_calibration_path_absolute(self) -> None:
        abs_path = str(Path("/abs/cal.yaml").resolve())
        config = DeviceConfig(target="x", num_qubits=1, calibration_path=abs_path)
        assert config.resolved_calibration_path == Path(abs_path)

    def test_resolved_calibration_path_relative_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "device.yaml"
        yaml_file.write_text(
            "target: superconducting_cz\nnum_qubits: 1\ncalibration_path: cal.yaml\n"
        )
        config = DeviceConfig.from_yaml(yaml_file)
        assert config.resolved_calibration_path == tmp_path / "cal.yaml"

    def test_resolved_calibration_path_relative_no_source(self) -> None:
        config = DeviceConfig(target="x", num_qubits=1, calibration_path="cal.yaml")
        assert config.resolved_calibration_path == Path.cwd() / "cal.yaml"


# ---------------------------------------------------------------------------
# Framework Protocol
# ---------------------------------------------------------------------------


class TestFrameworkProtocol:
    def test_stub_satisfies_protocol(self) -> None:
        fw = _StubFramework("test", frozenset({"target_a"}))
        assert isinstance(fw, Framework)

    def test_qua_satisfies_protocol(self) -> None:
        fw = QUAFramework()
        assert isinstance(fw, Framework)

    def test_qubic_satisfies_protocol(self) -> None:
        fw = QubiCFramework()
        assert isinstance(fw, Framework)


# ---------------------------------------------------------------------------
# FrameworkRegistry
# ---------------------------------------------------------------------------


class TestFrameworkRegistry:
    def test_register_and_get(self) -> None:
        registry = FrameworkRegistry()
        fw = _StubFramework("alpha", frozenset({"t"}))
        registry.register(fw)
        assert registry.get("alpha") is fw

    def test_register_duplicate_raises(self) -> None:
        registry = FrameworkRegistry()
        fw = _StubFramework("alpha", frozenset({"t"}))
        registry.register(fw)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(fw)

    def test_get_unknown_raises(self) -> None:
        registry = FrameworkRegistry()
        registry._discovered = True
        with pytest.raises(ConfigError, match="Unknown framework"):
            registry.get("nonexistent")

    def test_detect_explicit_framework(self) -> None:
        registry = FrameworkRegistry()
        fw = _StubFramework("alpha", frozenset({"superconducting_cz"}))
        registry.register(fw)
        config = DeviceConfig(
            framework="alpha", target="superconducting_cz", num_qubits=3
        )
        assert registry.detect(config) is fw

    def test_detect_by_target(self) -> None:
        registry = FrameworkRegistry()
        fw = _StubFramework("alpha", frozenset({"superconducting_cz"}))
        registry.register(fw)
        config = DeviceConfig(target="superconducting_cz", num_qubits=3)
        assert registry.detect(config) is fw

    def test_detect_no_match_raises(self) -> None:
        registry = FrameworkRegistry()
        registry._discovered = True
        config = DeviceConfig(target="unknown_target", num_qubits=1)
        with pytest.raises(ConfigError, match="No framework supports"):
            registry.detect(config)

    def test_detect_ambiguous_raises(self) -> None:
        registry = FrameworkRegistry()
        registry.register(_StubFramework("fw1", frozenset({"superconducting_cz"})))
        registry.register(_StubFramework("fw2", frozenset({"superconducting_cz"})))
        config = DeviceConfig(target="superconducting_cz", num_qubits=1)
        with pytest.raises(ConfigError, match="Multiple frameworks"):
            registry.detect(config)

    def test_registered_names(self) -> None:
        registry = FrameworkRegistry()
        registry.register(_StubFramework("beta", frozenset({"t"})))
        registry.register(_StubFramework("alpha", frozenset({"u"})))
        assert registry.registered_names == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# QUAFramework stub
# ---------------------------------------------------------------------------


class TestQUAFramework:
    def test_name_and_targets(self) -> None:
        fw = QUAFramework()
        assert fw.name == "qua"
        assert "superconducting_cz" in fw.supported_targets
        assert "superconducting_iswap" in fw.supported_targets

    def test_validate_unsupported_target(self) -> None:
        fw = QUAFramework()
        config = DeviceConfig(target="trapped_ion", num_qubits=3, opx_host="localhost")
        errors = fw.validate_config(config)
        assert any("not supported" in e for e in errors)

    def test_validate_missing_calibration(self) -> None:
        fw = QUAFramework()
        config = DeviceConfig(
            target="superconducting_cz", num_qubits=3, opx_host="localhost"
        )
        errors = fw.validate_config(config)
        assert any("calibration_path" in e for e in errors)

    def test_validate_missing_opx_host(self, tmp_path: Path) -> None:
        fw = QUAFramework()
        cal = tmp_path / "cal.yaml"
        cal.write_text("qubits: []\n")
        config = DeviceConfig(
            target="superconducting_cz",
            num_qubits=3,
            calibration_path=str(cal),
        )
        errors = fw.validate_config(config)
        assert any("opx_host" in e for e in errors)

    def test_validate_calibration_file_not_found(self) -> None:
        fw = QUAFramework()
        config = DeviceConfig(
            target="superconducting_cz",
            num_qubits=3,
            calibration_path="/nonexistent/cal.yaml",
            opx_host="localhost",
        )
        errors = fw.validate_config(config)
        assert any("not found" in e for e in errors)

    def test_validate_valid_config(self, tmp_path: Path) -> None:
        fw = QUAFramework()
        cal = tmp_path / "cal.yaml"
        cal.write_text("qubits: []\n")
        config = DeviceConfig(
            target="superconducting_cz",
            num_qubits=3,
            calibration_path=str(cal),
            opx_host="192.168.1.100",
        )
        errors = fw.validate_config(config)
        assert errors == []

    def test_create_executor_raises_not_implemented(self) -> None:
        fw = QUAFramework()
        config = DeviceConfig(target="superconducting_cz", num_qubits=3)
        with pytest.raises(NotImplementedError):
            fw.create_executor(config, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# QubiCFramework stub
# ---------------------------------------------------------------------------


class TestQubiCFramework:
    def test_name_and_targets(self) -> None:
        fw = QubiCFramework()
        assert fw.name == "qubic"
        assert "superconducting_cz" in fw.supported_targets
        assert "superconducting_cnot" in fw.supported_targets

    def test_validate_unsupported_target(self) -> None:
        fw = QubiCFramework()
        config = DeviceConfig(
            target="trapped_ion",
            num_qubits=3,
            classifier_path="/classifiers",
            rpc_host="localhost",
        )
        errors = fw.validate_config(config)
        assert any("not supported" in e for e in errors)

    def test_validate_missing_calibration(self) -> None:
        fw = QubiCFramework()
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            classifier_path="/classifiers",
            rpc_host="localhost",
        )
        errors = fw.validate_config(config)
        assert any("calibration_path" in e for e in errors)

    def test_validate_missing_classifier_path(self, tmp_path: Path) -> None:
        fw = QubiCFramework()
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(cal),
            rpc_host="localhost",
        )
        errors = fw.validate_config(config)
        assert any("classifier_path" in e for e in errors)

    def test_validate_rpc_mode_missing_host(self, tmp_path: Path) -> None:
        fw = QubiCFramework()
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(cal),
            classifier_path="/classifiers",
            runner_mode="rpc",
        )
        errors = fw.validate_config(config)
        assert any("rpc_host" in e for e in errors)

    def test_validate_local_mode_missing_xsa_commit(self, tmp_path: Path) -> None:
        fw = QubiCFramework()
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(cal),
            classifier_path="/classifiers",
            runner_mode="local",
        )
        errors = fw.validate_config(config)
        assert any("xsa_commit" in e for e in errors)

    def test_validate_local_mode_sim_bypasses_xsa(self, tmp_path: Path) -> None:
        fw = QubiCFramework()
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(cal),
            classifier_path="/classifiers",
            runner_mode="local",
            use_sim=True,
        )
        errors = fw.validate_config(config)
        assert errors == []

    def test_validate_unknown_runner_mode(self, tmp_path: Path) -> None:
        fw = QubiCFramework()
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(cal),
            classifier_path="/classifiers",
            runner_mode="cloud",
        )
        errors = fw.validate_config(config)
        assert any("Unknown runner_mode" in e for e in errors)

    def test_validate_valid_rpc_config(self, tmp_path: Path) -> None:
        fw = QubiCFramework()
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path=str(cal),
            classifier_path="/classifiers",
            rpc_host="10.0.0.42",
            rpc_port=9095,
        )
        errors = fw.validate_config(config)
        assert errors == []

    def test_validate_calibration_file_not_found(self) -> None:
        fw = QubiCFramework()
        config = DeviceConfig(
            target="superconducting_cnot",
            num_qubits=3,
            calibration_path="/nonexistent/qubitcfg.json",
            classifier_path="/classifiers",
            rpc_host="localhost",
        )
        errors = fw.validate_config(config)
        assert any("not found" in e for e in errors)

    def test_create_executor_raises_not_implemented(self) -> None:
        fw = QubiCFramework()
        config = DeviceConfig(target="superconducting_cnot", num_qubits=3)
        with pytest.raises(NotImplementedError):
            fw.create_executor(config, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# default_registry
# ---------------------------------------------------------------------------


class TestDefaultRegistry:
    def test_contains_qua_and_qubic(self) -> None:
        registry = default_registry()
        assert "qua" in registry.registered_names
        assert "qubic" in registry.registered_names

    def test_superconducting_cz_ambiguous_without_explicit_framework(self) -> None:
        registry = default_registry()
        config = DeviceConfig(target="superconducting_cz", num_qubits=3)
        with pytest.raises(ConfigError, match="Multiple frameworks"):
            registry.detect(config)

    def test_superconducting_cz_explicit_qua(self) -> None:
        registry = default_registry()
        config = DeviceConfig(
            framework="qua", target="superconducting_cz", num_qubits=3
        )
        fw = registry.detect(config)
        assert fw.name == "qua"

    def test_superconducting_cz_explicit_qubic(self) -> None:
        registry = default_registry()
        config = DeviceConfig(
            framework="qubic", target="superconducting_cz", num_qubits=3
        )
        fw = registry.detect(config)
        assert fw.name == "qubic"

    def test_superconducting_cnot_autodetects_qubic(self) -> None:
        registry = default_registry()
        config = DeviceConfig(target="superconducting_cnot", num_qubits=3)
        fw = registry.detect(config)
        assert fw.name == "qubic"

    def test_superconducting_iswap_autodetects_qua(self) -> None:
        registry = default_registry()
        config = DeviceConfig(target="superconducting_iswap", num_qubits=3)
        fw = registry.detect(config)
        assert fw.name == "qua"


# ---------------------------------------------------------------------------
# load_executor integration
# ---------------------------------------------------------------------------


class TestLoadExecutorWithDeviceConfig:
    def test_device_config_resolves_framework(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """load_executor reaches the framework's create_executor."""
        cal = tmp_path / "cal.yaml"
        cal.write_text("qubits: []\n")
        device_yaml = tmp_path / "device.yaml"
        device_yaml.write_text(
            "framework: qua\n"
            "target: superconducting_cz\n"
            "num_qubits: 3\n"
            f"calibration_path: {cal}\n"
            "opx_host: localhost\n"
        )

        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_DEVICE_CONFIG", str(device_yaml))
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        from self_service.server.config import Settings

        settings = Settings()
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            load_executor(settings)

    def test_executor_factory_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CODA_EXECUTOR_FACTORY is used even when CODA_DEVICE_CONFIG is set."""
        device_yaml = tmp_path / "device.yaml"
        device_yaml.write_text(
            "framework: qua\ntarget: superconducting_cz\nnum_qubits: 3\n"
        )

        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_DEVICE_CONFIG", str(device_yaml))
        monkeypatch.setenv(
            "CODA_EXECUTOR_FACTORY",
            "self_service.server.executor:NoopExecutor",
        )

        from self_service.server.config import Settings

        settings = Settings()
        executor = load_executor(settings)
        assert hasattr(executor, "run")

    def test_no_config_returns_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-token")
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)
        monkeypatch.delenv("CODA_DEVICE_CONFIG", raising=False)

        from self_service.server.config import Settings

        settings = Settings()
        executor = load_executor(settings)
        assert isinstance(executor, NoopExecutor)

    def test_device_config_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_DEVICE_CONFIG", "/nonexistent/device.yaml")
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        from self_service.server.config import Settings

        settings = Settings()
        with pytest.raises(ExecutorError, match="not found"):
            load_executor(settings)

    def test_device_config_qubic_resolves_framework(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """load_executor reaches the QubiC framework's create_executor."""
        cal = tmp_path / "qubitcfg.json"
        cal.write_text("{}")
        device_yaml = tmp_path / "device.yaml"
        device_yaml.write_text(
            "framework: qubic\n"
            "target: superconducting_cnot\n"
            "num_qubits: 3\n"
            f"calibration_path: {cal}\n"
            "classifier_path: /classifiers\n"
            "rpc_host: localhost\n"
        )

        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_DEVICE_CONFIG", str(device_yaml))
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        from self_service.server.config import Settings

        settings = Settings()
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            load_executor(settings)

    def test_device_config_validation_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Validation errors from the framework are surfaced as ExecutorError."""
        device_yaml = tmp_path / "device.yaml"
        device_yaml.write_text(
            "framework: qua\ntarget: superconducting_cz\nnum_qubits: 3\n"
        )

        monkeypatch.setenv("CODA_SELF_SERVICE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_DEVICE_CONFIG", str(device_yaml))
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        from self_service.server.config import Settings

        settings = Settings()
        with pytest.raises(ExecutorError, match="validation failed"):
            load_executor(settings)
