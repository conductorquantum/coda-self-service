"""Pluggable execution backend for quantum job processing.

The :class:`JobExecutor` protocol defines the single ``run`` method that
backends must implement.  A backend can be anything from a hardware QPU
driver to a simulator -- the consumer doesn't care.

Executor resolution order (in :func:`load_executor`):

1. If ``CODA_EXECUTOR_FACTORY`` is set, import the dotted path and use
   it as either a pre-built executor instance (has ``.run``) or a
   factory callable.
2. If ``settings.device_config`` provides an ``executor_factory`` value,
   use that.
3. Scan installed packages for the convention
   ``<pkg>.executor_factory:create_executor``.  If exactly one match is
   found, use it automatically.  If multiple match, warn and fall back.
4. Fall back to :class:`NoopExecutor`, which returns a deterministic
   all-zeros bitstring for every job.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from coda_node.errors import ExecutorError
from coda_node.server.ir import NativeGateIR

if TYPE_CHECKING:
    from coda_node.server.config import Settings

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


@runtime_checkable
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


def _instantiate_factory(import_path: str, settings: Settings) -> JobExecutor:
    """Import and instantiate the executor at *import_path*."""
    target = _load_attr(import_path)
    if hasattr(target, "run"):
        return cast(JobExecutor, target)

    if not callable(target):
        raise ExecutorError(f"Executor target {import_path!r} is not callable")

    parameters = inspect.signature(target).parameters
    executor = target(settings) if parameters else target()
    if not hasattr(executor, "run"):
        raise ExecutorError(f"Executor factory {import_path!r} did not return a runner")
    return cast(JobExecutor, executor)


def _discover_executor_factories() -> list[str]:
    """Scan installed packages for the ``create_executor`` convention.

    Iterates over importable top-level packages and checks whether
    ``<pkg>.executor_factory`` exists with a callable ``create_executor``.
    Returns a list of ``module:attr`` import paths.
    """
    try:
        from importlib.metadata import packages_distributions
    except ImportError:
        return []

    candidates: list[str] = []
    for pkg in packages_distributions():
        if "." in pkg or pkg.startswith("_") or pkg == "coda_node":
            continue
        module_name = f"{pkg}.executor_factory"
        try:
            spec = importlib.util.find_spec(module_name)
        except (ModuleNotFoundError, ValueError):
            continue
        if spec is None:
            continue
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            logger.warning(
                "Failed to import executor_factory module %r, skipping",
                module_name,
                exc_info=True,
            )
            continue
        factory = getattr(mod, "create_executor", None)
        if factory is not None and callable(factory):
            candidates.append(f"{module_name}:create_executor")

    return candidates


def load_executor(settings: Settings) -> JobExecutor:
    """Resolve and instantiate the configured execution backend.

    Resolution order:

    1. If ``settings.executor_factory`` is set, import and use it
       (pre-built executor or factory callable).
    2. If ``settings.device_config`` provides an ``executor_factory``
       value, import and use it.
    3. Scan installed packages for a conventional
       ``<pkg>.executor_factory:create_executor`` factory.  Use it if
       exactly one match is found; warn and skip if multiple match.
    4. Fall back to :class:`NoopExecutor` with a warning.

    Args:
        settings: Runtime settings.

    Returns:
        An object satisfying the :class:`JobExecutor` protocol.

    Raises:
        ExecutorError: If the configured executor cannot be loaded.
    """
    if settings.executor_factory:
        return _instantiate_factory(settings.executor_factory, settings)

    discovered = _discover_executor_factories()

    if len(discovered) == 1:
        logger.info("Auto-discovered executor factory: %s", discovered[0])
        return _instantiate_factory(discovered[0], settings)

    if len(discovered) > 1:
        logger.warning(
            "Multiple executor factories discovered (%s); "
            "set CODA_EXECUTOR_FACTORY to choose one. Using NoopExecutor.",
            ", ".join(discovered),
        )
        return NoopExecutor()

    logger.warning(
        "No executor configured (set CODA_EXECUTOR_FACTORY); using NoopExecutor"
    )
    return NoopExecutor()
