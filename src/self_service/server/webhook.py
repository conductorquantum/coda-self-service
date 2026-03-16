"""Authenticated webhook delivery for job results and errors.

After a job completes (or fails), the result is POST-ed to a Coda
callback URL as a signed JSON payload.  Each request carries a fresh
short-lived JWT so the cloud can verify the sender.

Delivery includes exponential-backoff retry for transient server errors
(5xx) and transport failures.  Client errors (4xx) are raised
immediately since retrying them would be pointless.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from self_service.server.auth import sign_token

logger = logging.getLogger(__name__)

__all__ = ["WebhookClient", "WebhookPayload"]

WebhookPayloadValue = dict[str, int] | float | int | str

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0


@dataclass(frozen=True, slots=True)
class WebhookPayload:
    """Immutable container for a job result or error sent via webhook.

    Only non-``None`` optional fields are included when serialized with
    :meth:`to_dict`, keeping the JSON payload minimal.
    """

    job_id: str
    status: str
    counts: dict[str, int] | None = None
    execution_time_ms: float | None = None
    shots_completed: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, WebhookPayloadValue]:
        """Serialize to a dict, omitting ``None``-valued optional fields."""
        result: dict[str, WebhookPayloadValue] = {
            "job_id": self.job_id,
            "status": self.status,
        }
        if self.counts is not None:
            result["counts"] = self.counts
        if self.execution_time_ms is not None:
            result["execution_time_ms"] = self.execution_time_ms
        if self.shots_completed is not None:
            result["shots_completed"] = self.shots_completed
        if self.error is not None:
            result["error"] = self.error
        return result


class WebhookClient:
    """Send signed job results to Coda callback URLs.

    Maintains a long-lived :class:`httpx.AsyncClient` for connection
    pooling and handles JWT signing, serialization, and retry logic.

    Args:
        qpu_id: QPU identifier used as the JWT ``sub`` claim.
        jwt_private_key: PEM-encoded RSA private key for signing.
        jwt_key_id: ``kid`` header value for the JWT.
        timeout: HTTP request timeout in seconds.
        max_retries: Maximum number of delivery attempts per webhook.
    """

    def __init__(
        self,
        qpu_id: str,
        jwt_private_key: str,
        jwt_key_id: str,
        timeout: float = 30.0,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._qpu_id = qpu_id
        self._jwt_private_key = jwt_private_key
        self._jwt_key_id = jwt_key_id
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def _post_with_retry(
        self, url: str, body: dict[str, WebhookPayloadValue]
    ) -> None:
        """POST *body* to *url* with JWT auth, retrying on 5xx and transport errors."""
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            token = sign_token(
                self._qpu_id, self._jwt_private_key, key_id=self._jwt_key_id
            )
            try:
                response = await self._client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                return
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code < 500
                ):
                    raise
                delay = _BACKOFF_BASE * (_BACKOFF_FACTOR ** (attempt - 1))
                logger.warning(
                    "Webhook POST to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    url,
                    attempt,
                    self._max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc

    async def send_result(self, callback_url: str, payload: WebhookPayload) -> None:
        """Deliver a job result to the Coda cloud with retry.

        Args:
            callback_url: The URL provided in the original job message.
            payload: Result data to POST as JSON.

        Raises:
            httpx.HTTPStatusError: On non-retryable (4xx) responses.
            httpx.TransportError: After all retry attempts are exhausted.
        """
        await self._post_with_retry(callback_url, payload.to_dict())

    async def send_error(self, callback_url: str, job_id: str, error: str) -> None:
        """Convenience wrapper to report a job failure."""
        await self.send_result(
            callback_url,
            WebhookPayload(job_id=job_id, status="failed", error=error),
        )

    async def close(self) -> None:
        """Shut down the underlying HTTP connection pool."""
        await self._client.aclose()
