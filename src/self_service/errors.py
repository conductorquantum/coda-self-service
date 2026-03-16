"""Shared exception hierarchy for coda-self-service.

All domain-specific exceptions inherit from :class:`CodaError` so that
callers can distinguish expected operational errors from unexpected bugs
with a single ``except CodaError`` clause.
"""

__all__ = [
    "AuthError",
    "CodaError",
    "ConfigError",
    "ExecutorError",
    "SelfServiceError",
    "VPNError",
    "WebhookError",
]


class CodaError(Exception):
    """Base exception for all coda-self-service errors."""


class ConfigError(CodaError):
    """Invalid or missing configuration."""


class AuthError(CodaError):
    """JWT authentication failure."""


class VPNError(CodaError):
    """VPN tunnel or health check failure."""


class SelfServiceError(VPNError):
    """Self-service bootstrap or reconnect failure."""


class ExecutorError(CodaError):
    """Executor loading or job execution failure."""


class WebhookError(CodaError):
    """Webhook delivery failure."""
