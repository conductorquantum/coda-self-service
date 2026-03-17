"""QubiC framework for LBNL QubiC-based quantum hardware.

Translates :class:`NativeGateIR` circuits into QubiC gate-level
instructions and executes them via the QubiC stack (RPC or local).

QubiC supports two IR targets:

- ``superconducting_cz`` — generic CZ-based IR, lowered via ZXZXZ
  decomposition and H-CNOT-H CZ synthesis.
- ``superconducting_cnot`` — native QubiC gates (x90, y_minus_90,
  virtual_z, cnot) passed through directly.

This module provides a stub :class:`QubiCFramework` that will be fully
implemented once the pipeline components (device derivation, circuit
translator, RPC runner) are integrated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from self_service.frameworks.base import DeviceConfig

if TYPE_CHECKING:
    from self_service.server.config import Settings
    from self_service.server.executor import JobExecutor

__all__ = ["QubiCFramework"]

_SUPPORTED_TARGETS = frozenset({"superconducting_cz", "superconducting_cnot"})


class QubiCFramework:
    """LBNL QubiC execution framework (stub).

    Once completed, this framework will:

    1. Parse ``qubitcfg.json`` to derive a ``QubiCDeviceSpec`` (BFS
       over the calibrated connectivity graph).
    2. Translate IR circuits into QubiC gate-level programs.
    3. Execute via ``JobManager`` (RPC client or local runner).
    4. Normalize measurement counts back to IR qubit order.
    """

    @property
    def name(self) -> str:
        return "qubic"

    @property
    def supported_targets(self) -> frozenset[str]:
        return _SUPPORTED_TARGETS

    def validate_config(self, device_config: DeviceConfig) -> list[str]:
        errors: list[str] = []

        if device_config.target not in _SUPPORTED_TARGETS:
            errors.append(
                f"Target {device_config.target!r} not supported by QubiC framework. "
                f"Supported: {sorted(_SUPPORTED_TARGETS)}"
            )

        cal_path = device_config.resolved_calibration_path
        if cal_path is None:
            errors.append(
                "calibration_path is required for the QubiC framework "
                "(must point to qubitcfg.json)"
            )
        elif not cal_path.exists():
            errors.append(f"Calibration file not found: {cal_path}")

        if not device_config.get_option("classifier_path"):
            errors.append("classifier_path is required (set in device config)")

        runner_mode = device_config.get_option("runner_mode", "rpc")
        if runner_mode == "rpc":
            if not device_config.get_option("rpc_host"):
                errors.append("rpc_host is required when runner_mode is 'rpc'")
        elif runner_mode == "local":
            use_sim = device_config.get_option("use_sim", False)
            if not use_sim and not device_config.get_option("xsa_commit"):
                errors.append(
                    "xsa_commit is required for local QubiC execution "
                    "unless use_sim is true"
                )
        else:
            errors.append(
                f"Unknown runner_mode {runner_mode!r}. Must be 'rpc' or 'local'."
            )

        return errors

    def create_executor(
        self, device_config: DeviceConfig, settings: Settings
    ) -> JobExecutor:
        raise NotImplementedError(
            "QubiC executor not yet implemented. "
            "The full pipeline (device derivation, translator, runner) "
            "will be integrated from stanza-private."
        )
