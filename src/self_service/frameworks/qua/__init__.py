"""QUA framework for Quantum Machines OPX hardware.

Translates :class:`NativeGateIR` circuits into QUA programs via a
pulse-mapping pipeline and executes them on an OPX controller.

This module provides a stub :class:`QUAFramework` that will be fully
implemented once the pipeline components (pulse mapper, config builder,
shot collector, calibration store) are integrated from ``stanza``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from self_service.frameworks.base import DeviceConfig

if TYPE_CHECKING:
    from self_service.server.config import Settings
    from self_service.server.executor import JobExecutor

__all__ = ["QUAFramework"]

_SUPPORTED_TARGETS = frozenset({"superconducting_cz", "superconducting_iswap"})


class QUAFramework:
    """Quantum Machines OPX execution framework (stub).

    Once completed, this framework will:

    1. Load per-qubit calibration from a YAML file.
    2. Map IR gates to pulse operations via ``PulseMapper``.
    3. Build a QUA config and program.
    4. Execute on an OPX controller and collect shot results.
    """

    @property
    def name(self) -> str:
        return "qua"

    @property
    def supported_targets(self) -> frozenset[str]:
        return _SUPPORTED_TARGETS

    def validate_config(self, device_config: DeviceConfig) -> list[str]:
        errors: list[str] = []

        if device_config.target not in _SUPPORTED_TARGETS:
            errors.append(
                f"Target {device_config.target!r} not supported by QUA framework. "
                f"Supported: {sorted(_SUPPORTED_TARGETS)}"
            )

        cal_path = device_config.resolved_calibration_path
        if cal_path is None:
            errors.append("calibration_path is required for the QUA framework")
        elif not cal_path.exists():
            errors.append(f"Calibration file not found: {cal_path}")

        if not device_config.get_option("opx_host"):
            errors.append("opx_host is required (set in device config)")

        return errors

    def create_executor(
        self, device_config: DeviceConfig, settings: Settings
    ) -> JobExecutor:
        raise NotImplementedError(
            "QUA executor not yet implemented. "
            "The full pipeline will be added in a subsequent commit."
        )
