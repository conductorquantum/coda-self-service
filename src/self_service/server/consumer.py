"""Redis Streams consumer that reads jobs and dispatches them to an executor.

The consumer uses a Redis consumer group so that multiple workers can
share a single stream.  On startup it performs crash recovery for
messages that were claimed but never acknowledged (e.g. after an
unclean shutdown).

Message lifecycle:

1. ``XREADGROUP`` blocks for new messages on ``qpu:<qpu_id>:jobs``.
2. Each message is deserialized into a :class:`NativeGateIR` and handed
   to the :class:`~self_service.server.executor.JobExecutor`.
3. The result (or error) is posted back via
   :class:`~self_service.server.webhook.WebhookClient`.
4. The message is ``XACK``-ed regardless of success or failure so it
   does not re-enter the pending list.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar, cast

import redis.asyncio as aioredis

from self_service.server.ir import NativeGateIR
from self_service.server.webhook import WebhookPayload

if TYPE_CHECKING:
    from self_service.server.executor import JobExecutor
    from self_service.server.webhook import WebhookClient

logger = logging.getLogger(__name__)

__all__ = ["RedisConsumer"]

T = TypeVar("T")

_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_MAX = 60.0
_PENDING_RECHECK_SECS = 60.0


async def _await_if_needed(value: T | Awaitable[T]) -> T:
    """Await *value* if it is awaitable, otherwise return it directly."""
    if inspect.isawaitable(value):
        return await cast(Awaitable[T], value)
    return value


class RedisConsumer:
    """Consume jobs from a Coda Redis stream and dispatch to an executor.

    Args:
        redis: An async Redis client instance.
        runner: The execution backend that processes each job.
        webhook: Client for posting results back to the Coda cloud.
        qpu_id: QPU identifier used to derive stream and group names.
        consumer_name: Name of this consumer within the group (for
            distinguishing workers in a multi-process deployment).
        crash_recovery_threshold_ms: Minimum idle time (in ms) before a
            pending message is considered abandoned and eligible for
            reprocessing.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        runner: JobExecutor,
        webhook: WebhookClient,
        qpu_id: str,
        consumer_name: str = "worker-0",
        crash_recovery_threshold_ms: int = 60_000,
    ) -> None:
        self._redis = redis
        self._runner = runner
        self._webhook = webhook
        self._qpu_id = qpu_id
        self._consumer_name = consumer_name
        self._crash_recovery_threshold_ms = crash_recovery_threshold_ms
        self._stream = f"qpu:{qpu_id}:jobs"
        self._group = f"qpu:{qpu_id}:workers"
        self._running = False
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self.current_job_id: str | None = None
        self.last_job_at: str | None = None
        self.redis_healthy = True

    @staticmethod
    def _decode_fields(fields: Mapping[object, object]) -> dict[str, str]:
        """Normalise byte keys/values returned when *decode_responses* is off."""
        return {
            (k.decode() if isinstance(k, bytes) else str(k)): (
                v.decode() if isinstance(v, bytes) else str(v)
            )
            for k, v in fields.items()
        }

    async def setup(self) -> None:
        """Create the consumer group if it does not already exist.

        The stream is created automatically (``mkstream=True``) so that
        the consumer can start before any jobs have been enqueued.
        """
        try:
            await self._redis.xgroup_create(
                name=self._stream,
                groupname=self._group,
                id="0",
                mkstream=True,
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def recover_pending(self) -> int:
        """Re-process messages left pending after an unclean shutdown.

        Because the query is scoped to ``consumername=self._consumer_name``,
        these are exclusively *our own* unacknowledged messages.  There is
        no risk of stealing work from a peer, so every pending message is
        recovered regardless of idle time.

        Returns:
            The number of messages that were reprocessed.
        """
        recovered = 0
        pending = await self._redis.xpending_range(
            name=self._stream,
            groupname=self._group,
            consumername=self._consumer_name,
            min="-",
            max="+",
            count=100,
        )

        for entry in pending:
            message_id = entry["message_id"]
            messages = await self._redis.xrange(
                self._stream, min=message_id, max=message_id
            )
            if messages:
                _, fields = messages[0]
                await self._process_message(message_id, fields)
                recovered += 1

        return recovered

    async def consume_loop(self) -> None:
        """Run the main consume loop until :meth:`stop` is called.

        On each iteration the loop blocks (up to 5 s) for a new message
        via ``XREADGROUP``.  Connection errors trigger exponential
        backoff (1 s → 60 s max); unexpected errors trigger a 1 s
        backoff.  The loop sets :attr:`redis_healthy` to reflect the
        current connection state.
        """
        self._running = True
        await self.setup()
        await self.recover_pending()

        consecutive_failures = 0
        last_pending_check = time.monotonic()
        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer_name,
                    streams={self._stream: ">"},
                    count=1,
                    block=5000,
                )
                self.redis_healthy = True
                consecutive_failures = 0

                if not messages:
                    now = time.monotonic()
                    if now - last_pending_check >= _PENDING_RECHECK_SECS:
                        await self.recover_pending()
                        last_pending_check = now
                    continue

                for _stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        await self._process_message(message_id, fields)
            except (ConnectionError, OSError, aioredis.ConnectionError):
                self.redis_healthy = False
                consecutive_failures += 1
                delay = min(
                    _BACKOFF_BASE * (_BACKOFF_FACTOR ** (consecutive_failures - 1)),
                    _BACKOFF_MAX,
                )
                logger.warning(
                    "Redis connection lost (attempt %d), retrying in %.1fs",
                    consecutive_failures,
                    delay,
                )
                await asyncio.sleep(delay)
            except Exception:
                logger.exception("Consumer loop error")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal the consume loop to exit after the current iteration."""
        self._running = False

    async def drain(self, timeout: float = 30.0) -> bool:
        """Wait for any in-flight job to finish, then stop.

        Args:
            timeout: Maximum seconds to wait for the current job.

        Returns:
            ``True`` if drained cleanly, ``False`` if the timeout
            expired with a job still running.
        """
        self.stop()
        try:
            await asyncio.wait_for(self._idle_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def _safe_hset(self, key: str, mapping: dict[str, str]) -> bool:
        """Attempt HSET, return False on connection error."""
        try:
            await _await_if_needed(self._redis.hset(key, mapping=mapping))
            return True
        except (ConnectionError, OSError, aioredis.ConnectionError):
            logger.warning("Redis unavailable, skipping status update for %s", key)
            return False

    async def _safe_xack(self, message_id: str) -> bool:
        """Attempt XACK, return False on connection error."""
        try:
            await self._redis.xack(self._stream, self._group, message_id)
            return True
        except (ConnectionError, OSError, aioredis.ConnectionError):
            logger.warning(
                "Redis unavailable, could not XACK %s (will be retried via crash recovery)",
                message_id,
            )
            return False

    async def _process_message(
        self, message_id: str, fields: Mapping[object, object]
    ) -> None:
        """Deserialize, execute, and report a single job from the stream.

        Skips jobs already marked as completed.  On success, sends a
        result webhook; on failure, sends an error webhook.  The message
        is always acknowledged so it does not re-enter the pending list.
        Redis connection errors during status updates are logged but do
        not prevent webhook delivery.
        """
        decoded_fields = self._decode_fields(fields)
        try:
            job_id = decoded_fields["job_id"]
            callback_url = decoded_fields["callback_url"]
        except KeyError as exc:
            logger.error(
                "Malformed stream message %s (missing %s), skipping. Keys: %s",
                message_id,
                exc,
                sorted(decoded_fields.keys()),
            )
            await self._safe_xack(message_id)
            return

        status_raw = await _await_if_needed(
            self._redis.hget(f"qpu:job:{job_id}:status", "state")
        )
        status = (
            status_raw.decode()
            if isinstance(status_raw, bytes)
            else str(status_raw) if status_raw is not None else None
        )
        if status == "completed":
            await self._safe_xack(message_id)
            return

        self._idle_event.clear()
        self.current_job_id = job_id
        await self._safe_hset(
            f"qpu:job:{job_id}:status",
            {
                "state": "executing",
                "started_at": datetime.now(UTC).isoformat(),
                "message_id": message_id,
                "qpu_id": self._qpu_id,
            },
        )

        try:
            ir = NativeGateIR.from_json(decoded_fields["ir_json"])
            shots = int(decoded_fields["shots"])
            result = await self._runner.run(ir, shots)

            await self._safe_hset(
                f"qpu:job:{job_id}:status",
                {
                    "state": "completed",
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

            payload = WebhookPayload(
                job_id=job_id,
                status="completed",
                counts=result.counts,
                execution_time_ms=result.execution_time_ms,
                shots_completed=result.shots_completed,
            )
            await self._webhook.send_result(callback_url, payload)
            self.last_job_at = datetime.now(UTC).isoformat()
        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
            await self._safe_hset(
                f"qpu:job:{job_id}:status",
                {
                    "state": "failed",
                    "error": str(exc)[:500],
                    "failed_at": datetime.now(UTC).isoformat(),
                },
            )
            try:
                await self._webhook.send_error(callback_url, job_id, str(exc)[:500])
            except Exception:
                logger.exception("Failed to send error webhook for job %s", job_id)
        finally:
            await self._safe_xack(message_id)
            self.current_job_id = None
            self._idle_event.set()
