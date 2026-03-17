"""Framework protocol and device configuration model.

A *framework* translates hardware-agnostic :class:`NativeGateIR` circuits
into control-system-specific instructions (pulses, configs, programs) and
executes them on physical hardware.  Each framework declares which IR
targets it supports and how to validate a user-supplied device
configuration.

The :class:`DeviceConfig` model is the user's single entry point for
hardware setup.  It declares the framework and hardware target, points
to a calibration file, and carries framework-specific options as extra
fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

if TYPE_CHECKING:
    from self_service.server.config import Settings
    from self_service.server.executor import JobExecutor

__all__ = ["DeviceConfig", "Framework"]


class DeviceConfig(BaseModel):
    """User-supplied device configuration loaded from YAML.

    Standard fields are validated by Pydantic.  Any additional keys
    (framework-specific connection parameters, topology hints, etc.)
    are preserved in ``model_extra`` and accessible via
    :meth:`get_options`.

    Example YAML::

        framework: qua
        target: superconducting_cz
        num_qubits: 3
        calibration_path: ./calibration.yaml
        opx_host: 192.168.1.100
        opx_port: 80
    """

    model_config = ConfigDict(extra="allow")

    framework: str = ""
    target: str = Field(min_length=1)
    num_qubits: int = Field(ge=1, le=50)
    calibration_path: str = ""

    _source_dir: Path | None = PrivateAttr(default=None)

    def get_options(self) -> dict[str, Any]:
        """Return framework-specific options (extra fields not in the base schema)."""
        return dict(self.model_extra or {})

    def get_option(self, key: str, default: Any = None) -> Any:
        """Return a single framework-specific option, or *default*."""
        return (self.model_extra or {}).get(key, default)

    @property
    def resolved_calibration_path(self) -> Path | None:
        """Resolve *calibration_path* relative to the config file's directory.

        Returns ``None`` when *calibration_path* is empty.  Absolute paths
        are returned as-is.  Relative paths are resolved against the
        directory of the YAML file that was loaded (set by
        :meth:`from_yaml`), falling back to the current working directory
        for programmatically constructed instances.
        """
        if not self.calibration_path:
            return None
        p = Path(self.calibration_path)
        if p.is_absolute():
            return p
        return (self._source_dir or Path.cwd()) / p

    @classmethod
    def from_yaml(cls, path: str | Path) -> DeviceConfig:
        """Load and validate a device configuration from a YAML file.

        Relative paths inside the config (e.g. *calibration_path*) are
        resolved against *path*'s parent directory.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If the file does not contain a YAML mapping.
            pydantic.ValidationError: If the content fails schema validation.
            ImportError: If PyYAML is not installed.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for device config files. "
                "Install it with: pip install pyyaml"
            ) from None

        file_path = Path(path).resolve()
        raw = yaml.safe_load(file_path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(
                f"{file_path}: expected a YAML mapping, got {type(raw).__name__}"
            )

        config = cls.model_validate(raw)
        config._source_dir = file_path.parent
        return config


@runtime_checkable
class Framework(Protocol):
    """Protocol that hardware control frameworks must satisfy.

    A framework bridges the gap between :class:`NativeGateIR` and a
    specific control system (QUA for Quantum Machines OPX, Qiskit Pulse,
    etc.).  Implement this protocol and register it with
    :class:`~self_service.frameworks.registry.FrameworkRegistry` or
    expose it via a ``coda.frameworks`` entry point.
    """

    @property
    def name(self) -> str:
        """Short identifier (e.g. ``"qua"``, ``"qiskit_pulse"``)."""
        ...

    @property
    def supported_targets(self) -> frozenset[str]:
        """Set of IR target strings this framework can execute."""
        ...

    def validate_config(self, device_config: DeviceConfig) -> list[str]:
        """Return validation errors for *device_config* (empty = valid).

        Check that required connection parameters are present, calibration
        files exist and parse, and third-party packages are installed.
        """
        ...

    def create_executor(
        self, device_config: DeviceConfig, settings: Settings
    ) -> JobExecutor:
        """Construct an executor wired to the physical hardware.

        Raises:
            ExecutorError: If the executor cannot be created.
        """
        ...
