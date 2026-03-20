"""Periodic heartbeat reporter that keeps the QPU status "online".

The :class:`HeartbeatClient` runs a background loop that POSTs
authenticated status updates to the Coda cloud heartbeat endpoint
every *interval* seconds.  If the QPU misses several consecutive
heartbeats the cloud marks it offline, so this loop is essential for
maintaining QPU visibility.

The heartbeat payload mirrors the node's readiness state: current job,
last job timestamp, and Redis health.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

from self_service.server.auth import sign_token

if TYPE_CHECKING:
    from self_service.server.consumer import RedisConsumer

logger = logging.getLogger(__name__)

__all__ = ["HeartbeatClient"]

_DEFAULT_INTERVAL = 30
_HTTP_TIMEOUT = 10.0


class HeartbeatClient:
    """Send periodic authenticated heartbeats to the Coda cloud.

    Args:
        heartbeat_url: Full URL of the heartbeat endpoint.
        qpu_id: QPU identifier used as the JWT ``sub`` claim.
        jwt_private_key: PEM-encoded RSA private key for signing.
        jwt_key_id: ``kid`` header value for the JWT.
        consumer: The Redis consumer whose readiness state is reported.
        interval: Seconds between heartbeat POSTs.
        connectivity: Undirected qubit-topology edge list (e.g.
            ``[[0, 1], [1, 2]]``).  Sent with every heartbeat so the
            cloud compiler can perform topology-aware routing.
    """

    def __init__(
        self,
        heartbeat_url: str,
        qpu_id: str,
        jwt_private_key: str,
        jwt_key_id: str,
        consumer: RedisConsumer,
        interval: int = _DEFAULT_INTERVAL,
        connectivity: list[list[int]] | None = None,
    ) -> None:
        self._url = heartbeat_url
        self._qpu_id = qpu_id
        self._jwt_private_key = jwt_private_key
        self._jwt_key_id = jwt_key_id
        self._consumer = consumer
        self._interval = interval
        self._connectivity = connectivity
        self._running = False
        self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)

    async def _send(self) -> None:
        """POST a single heartbeat with current node status."""
        token = sign_token(self._qpu_id, self._jwt_private_key, key_id=self._jwt_key_id)
        body: dict[str, object] = {
            "current_job": self._consumer.current_job_id,
            "last_job_at": self._consumer.last_job_at,
            "redis_healthy": self._consumer.redis_healthy,
            "connectivity": self._connectivity,
        }
        response = await self._client.post(
            self._url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()

    async def run(self) -> None:
        """Run the heartbeat loop until :meth:`stop` is called."""
        self._running = True
        logger.info(
            "Heartbeat loop started (every %ds → %s)", self._interval, self._url
        )
        while self._running:
            try:
                await self._send()
                logger.debug("Heartbeat sent to %s", self._url)
            except Exception:
                logger.warning("Heartbeat to %s failed", self._url, exc_info=True)
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        """Signal the heartbeat loop to exit after the current iteration."""
        self._running = False

    async def close(self) -> None:
        """Shut down the underlying HTTP connection pool."""
        self.stop()
        await self._client.aclose()
