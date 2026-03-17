"""Pluggable hardware framework subsystem.

A *framework* bridges the gap between the hardware-agnostic
:class:`~self_service.server.ir.NativeGateIR` circuit format and a
specific control system (e.g. QUA for Quantum Machines OPX).  The
framework subsystem provides:

- A :class:`DeviceConfig` model that users create to describe their
  hardware, calibration data, and connection parameters.
- A :class:`Framework` protocol that framework authors implement.
- A :class:`FrameworkRegistry` with auto-detection that resolves the
  right framework from a device config.

Executor resolution order in
:func:`~self_service.server.executor.load_executor`:

1. ``CODA_EXECUTOR_FACTORY`` — explicit import path (existing).
2. ``CODA_DEVICE_CONFIG``   — YAML file → auto-detect framework.
3. Fallback to :class:`~self_service.server.executor.NoopExecutor`.
"""

from self_service.frameworks.base import DeviceConfig, Framework
from self_service.frameworks.registry import FrameworkRegistry, default_registry

__all__ = ["DeviceConfig", "Framework", "FrameworkRegistry", "default_registry"]
