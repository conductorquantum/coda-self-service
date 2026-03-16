"""Coda self-service: a standalone server runtime for quantum processing units.

This package provides everything needed to connect an execution backend
(QPU or simulator) to the Coda cloud platform.  It handles JWT-based
authentication, VPN tunnel management, Redis job consumption, and signed
webhook delivery so that backend authors only need to implement the
:class:`~self_service.server.executor.JobExecutor` protocol.

Typical usage::

    uv run coda start --token <bootstrap-token>
"""

from self_service.errors import CodaError
from self_service.server import app, create_app

__version__ = "0.1.0"
__all__ = ["CodaError", "__version__", "app", "create_app"]
