"""Server runtime: FastAPI app, configuration, job consumption, and webhooks.

Re-exports the application factory :func:`create_app` and the default
``app`` instance used by the ``coda start`` CLI command.
"""

from self_service.server.app import app, create_app

__all__ = ["app", "create_app"]
