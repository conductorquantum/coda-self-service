"""Pluggable execution backend for quantum job processing.

The :class:`JobExecutor` protocol defines the single ``run`` method that
backends must implement.  A backend can be anything from a hardware QPU
driver to a simulator -- the consumer doesn't care.

Executor resolution order (in :func:`load_executor`):

1. If ``CODA_EXECUTOR_FACTORY`` is set, import the dotted path and use
   it as either a pre-built executor instance (has ``.run``) or a
   factory callable.
2. If ``CODA_DEVICE_CONFIG`` points to a YAML file, auto-detect the
   appropriate framework and create an executor.
3. Otherwise fall back to :class:`NoopExecutor`, which returns a
   deterministic all-zeros bitstring for every job.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from self_service.errors import ExecutorError
from self_service.server.ir import NativeGateIR

if TYPE_CHECKING:
    from self_service.server.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["ExecutionResult", "JobExecutor", "NoopExecutor", "load_executor"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Measurement outcome returned by an executor.

    Attributes:
        counts: Mapping from bitstring (e.g. ``"010"``) to the number of
            times that outcome was observed.
        execution_time_ms: Wall-clock execution time in milliseconds.
        shots_completed: Total shots actually executed (may differ from
            the requested count if the backend applies shot budgeting).
    """

    counts: dict[str, int]
    execution_time_ms: float
    shots_completed: int


class JobExecutor(Protocol):
    """Protocol that all execution backends must satisfy.

    Implement a single async ``run`` method that accepts a validated IR
    program and returns an :class:`ExecutionResult`.
    """

    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        """Execute a quantum circuit and return measurement counts.

        Args:
            ir: A validated native-gate intermediate representation.
            shots: Number of measurement shots to perform.

        Returns:
            An :class:`ExecutionResult` with bitstring counts.
        """


class NoopExecutor:
    """Deterministic executor used for scaffolding and integration smoke tests."""

    async def run(self, ir: NativeGateIR, shots: int) -> ExecutionResult:
        """Return an all-zeros result for every circuit."""
        bitstring = "0" * len(ir.measurements)
        return ExecutionResult(
            counts={bitstring: shots},
            execution_time_ms=0.0,
            shots_completed=shots,
        )


def _load_attr(import_path: str) -> Any:
    """Import and return the attribute at *import_path* (``module:attr`` format)."""
    module_name, sep, attr_name = import_path.partition(":")
    if not sep or not module_name or not attr_name:
        raise ExecutorError(
            "CODA_EXECUTOR_FACTORY must look like 'package.module:factory_name'"
        )
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _load_from_factory(settings: Settings) -> JobExecutor:
    """Import and instantiate the executor from ``CODA_EXECUTOR_FACTORY``."""
    target = _load_attr(settings.executor_factory)
    if hasattr(target, "run"):
        return cast(JobExecutor, target)

    if not callable(target):
        raise ExecutorError(
            f"Executor target {settings.executor_factory!r} is not callable"
        )

    parameters = inspect.signature(target).parameters
    executor = target(settings) if parameters else target()
    if not hasattr(executor, "run"):
        raise ExecutorError(
            f"Executor factory {settings.executor_factory!r} did not return a runner"
        )
    return cast(JobExecutor, executor)


def _load_from_device_config(settings: Settings) -> JobExecutor:
    """Load the framework-based executor from ``CODA_DEVICE_CONFIG``."""
    from self_service.frameworks.base import DeviceConfig
    from self_service.frameworks.registry import default_registry

    try:
        config = DeviceConfig.from_yaml(settings.device_config)
    except FileNotFoundError:
        raise ExecutorError(
            f"Device config not found: {settings.device_config}"
        ) from None
    except Exception as exc:
        raise ExecutorError(
            f"Invalid device config {settings.device_config!r}: {exc}"
        ) from exc

    registry = default_registry()
    framework = registry.detect(config)

    errors = framework.validate_config(config)
    if errors:
        raise ExecutorError(
            f"Device config validation failed ({framework.name!r}):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return framework.create_executor(config, settings)


def load_executor(settings: Settings) -> JobExecutor:
    """Resolve and instantiate the configured execution backend.

    Resolution order:

    1. If ``settings.executor_factory`` is set, import and use it
       (pre-built executor or factory callable).
    2. If ``settings.device_config`` points to a YAML file, auto-detect
       the appropriate framework and create an executor.
    3. Fall back to :class:`NoopExecutor` with a warning.

    Args:
        settings: Runtime settings.

    Returns:
        An object satisfying the :class:`JobExecutor` protocol.

    Raises:
        ExecutorError: If the configured executor cannot be loaded.
        ConfigError: If the device config references an unknown framework.
    """
    if settings.executor_factory:
        return _load_from_factory(settings)

    if settings.device_config:
        return _load_from_device_config(settings)

    logger.warning(
        "No executor configured (set CODA_EXECUTOR_FACTORY or "
        "CODA_DEVICE_CONFIG); using NoopExecutor"
    )
    return NoopExecutor()
