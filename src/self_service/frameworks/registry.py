"""Framework registry and auto-detection.

Frameworks are registered either explicitly via
:meth:`FrameworkRegistry.register` or discovered from ``coda.frameworks``
`entry points`_.  The registry is queried by
:func:`~self_service.server.executor.load_executor` when
``CODA_DEVICE_CONFIG`` is set.

.. _entry points:
   https://packaging.python.org/en/latest/specifications/entry-points/
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from self_service.errors import ConfigError
from self_service.frameworks.base import DeviceConfig, Framework

logger = logging.getLogger(__name__)

__all__ = ["FrameworkRegistry", "default_registry"]

_ENTRY_POINT_GROUP = "coda.frameworks"


class FrameworkRegistry:
    """Maps framework names to :class:`Framework` instances.

    Built-in frameworks are registered eagerly by :func:`default_registry`.
    Third-party frameworks are discovered lazily from entry points on the
    first lookup or detect call.
    """

    def __init__(self) -> None:
        self._frameworks: dict[str, Framework] = {}
        self._discovered = False

    def register(self, framework: Framework) -> None:
        """Register a framework instance.

        Raises:
            ValueError: If a framework with the same name is already
                registered.
        """
        name = framework.name
        if name in self._frameworks:
            raise ValueError(f"Framework {name!r} is already registered")
        self._frameworks[name] = framework
        logger.debug("Registered framework %r", name)

    def get(self, name: str) -> Framework:
        """Look up a framework by name.

        Raises:
            ConfigError: If no framework with *name* is registered.
        """
        self._ensure_discovered()
        if name not in self._frameworks:
            available = sorted(self._frameworks)
            raise ConfigError(f"Unknown framework {name!r}. Available: {available}")
        return self._frameworks[name]

    def detect(self, device_config: DeviceConfig) -> Framework:
        """Resolve the framework for *device_config*.

        Resolution order:

        1. Explicit ``framework`` field in the config.
        2. Match ``target`` against each framework's
           ``supported_targets``.
        3. If ambiguous, raise asking the user to disambiguate.

        Raises:
            ConfigError: If no framework can be determined.
        """
        self._ensure_discovered()

        if device_config.framework:
            return self.get(device_config.framework)

        candidates = [
            fw
            for fw in self._frameworks.values()
            if device_config.target in fw.supported_targets
        ]

        if not candidates:
            available = sorted(self._frameworks)
            raise ConfigError(
                f"No framework supports target {device_config.target!r}. "
                f"Registered frameworks: {available}"
            )

        if len(candidates) > 1:
            names = sorted(fw.name for fw in candidates)
            raise ConfigError(
                f"Multiple frameworks support target "
                f"{device_config.target!r}: {names}. "
                f"Set 'framework' explicitly in the device config."
            )

        return candidates[0]

    @property
    def registered_names(self) -> list[str]:
        """Sorted list of registered framework names."""
        self._ensure_discovered()
        return sorted(self._frameworks)

    def _ensure_discovered(self) -> None:
        """Lazily discover entry-point frameworks on first access."""
        if self._discovered:
            return
        self._discovered = True
        for ep in entry_points(group=_ENTRY_POINT_GROUP):
            try:
                loaded = ep.load()
                instance = loaded() if isinstance(loaded, type) else loaded
                if instance.name not in self._frameworks:
                    self.register(instance)
            except Exception:
                logger.warning(
                    "Failed to load framework entry point %r",
                    ep.name,
                    exc_info=True,
                )


def default_registry() -> FrameworkRegistry:
    """Return a registry pre-populated with built-in frameworks.

    Built-in frameworks (e.g. QUA) are registered eagerly.  Third-party
    frameworks are discovered lazily from entry points on first lookup.
    """
    registry = FrameworkRegistry()

    try:
        from self_service.frameworks.qua import QUAFramework

        registry.register(QUAFramework())
    except Exception:
        logger.debug("QUA framework not available", exc_info=True)

    try:
        from self_service.frameworks.qubic import QubiCFramework

        registry.register(QubiCFramework())
    except Exception:
        logger.debug("QubiC framework not available", exc_info=True)

    return registry
