"""Tests for the Redis stream consumer."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis

import coda_node.server.consumer as consumer_module
from coda_node.server.consumer import RedisConsumer
from coda_node.server.executor import ExecutionResult


class MockRedis:
    def __init__(self) -> None:
        self._groups_created: set[str] = set()
        self._acked: list[str] = []
        self._hashes: dict[str, dict[str, str]] = {}
        self._values: dict[str, str] = {}

    async def xgroup_create(
        self, name: str, groupname: str, id: str, mkstream: bool = False
    ) -> None:
        if groupname in self._groups_created:
            import redis.asyncio as aioredis

            raise aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")
        self._groups_created.add(groupname)

    async def xpending_range(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min: str,
        max: str,
        count: int,
    ) -> list[dict[str, str | int]]:
        return []

    async def xrange(
        self, stream: str, min: str, max: str
    ) -> list[tuple[str, dict[str, str]]]:
        return []

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int = 1,
        block: int = 0,
    ) -> None:
        return None

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        self._acked.append(message_id)

    async def hget(self, name: str, key: str) -> str | None:
        return self._hashes.get(name, {}).get(key)

    async def hset(self, name: str, mapping: dict[str, str]) -> None:
        self._hashes.setdefault(name, {}).update(mapping)

    async def get(self, name: str) -> str | None:
        return self._values.get(name)


@pytest.fixture
def mock_redis() -> MockRedis:
    return MockRedis()


@pytest.fixture
def mock_runner() -> AsyncMock:
    runner = AsyncMock()
    runner.run = AsyncMock(
        return_value=ExecutionResult(
            counts={"00": 1024},
            execution_time_ms=150.0,
            shots_completed=1024,
        )
    )
    return runner


@pytest.fixture
def mock_webhook() -> AsyncMock:
    webhook = AsyncMock()
    webhook.send_result = AsyncMock()
    webhook.send_error = AsyncMock()
    return webhook


@pytest.fixture
def consumer(
    mock_redis: MockRedis, mock_runner: AsyncMock, mock_webhook: AsyncMock
) -> RedisConsumer:
    return RedisConsumer(
        redis=cast(aioredis.Redis, mock_redis),
        runner=mock_runner,
        webhook=mock_webhook,
        qpu_id="test-node",
    )


VALID_IR_JSON = (
    '{"version":"1.0","target":"cz","num_qubits":2,'
    '"gates":[{"gate":"cz","qubits":[0,1],"params":[]}],'
    '"measurements":[0,1],'
    '"metadata":{"source_hash":"abc123","compiled_at":"2026-01-01T00:00:00Z"}}'
)


class TestConsumer:
    async def test_setup_creates_group(
        self, consumer: RedisConsumer, mock_redis: MockRedis
    ) -> None:
        await consumer.setup()
        assert "qpu:test-node:workers" in mock_redis._groups_created

    async def test_processes_successful_job(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        await consumer._process_message(
            "msg-1",
            {
                "job_id": "job-1",
                "ir_json": VALID_IR_JSON,
                "shots": "1024",
                "callback_url": "https://example.com/callback",
            },
        )
        mock_runner.run.assert_called_once()
        mock_webhook.send_result.assert_called_once()
        assert "msg-1" in mock_redis._acked

    async def test_skips_completed_job(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
    ) -> None:
        mock_redis._hashes["qpu:job:job-1:status"] = {"state": "completed"}
        await consumer._process_message(
            "msg-2",
            {
                "job_id": "job-1",
                "ir_json": VALID_IR_JSON,
                "shots": "1024",
                "callback_url": "https://example.com/callback",
            },
        )
        mock_runner.run.assert_not_called()
        assert "msg-2" in mock_redis._acked

    async def test_skips_cancelled_job_before_execution(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_redis._values["qpu:job:cancelled:job-1"] = "1"
        await consumer._process_message(
            "msg-cancelled",
            {
                "job_id": "job-1",
                "ir_json": VALID_IR_JSON,
                "shots": "1024",
                "callback_url": "https://example.com/callback",
            },
        )
        mock_runner.run.assert_not_called()
        mock_webhook.send_result.assert_not_called()
        assert "msg-cancelled" in mock_redis._acked
        assert mock_redis._hashes["qpu:job:job-1:status"]["state"] == "cancelled"

    async def test_cancels_job_during_execution_and_skips_webhook(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_webhook: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class BlockingRunner:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.cancel_calls = 0

            async def run(self, ir, shots):
                self.started.set()
                await asyncio.Future()

            async def cancel_current_job(self) -> None:
                self.cancel_calls += 1

        runner = BlockingRunner()
        consumer._runner = runner  # type: ignore[assignment]
        monkeypatch.setattr(consumer_module, "_CANCEL_POLL_INTERVAL_SECS", 0.01)

        task = asyncio.create_task(
            consumer._process_message(
                "msg-inflight-cancel",
                {
                    "job_id": "job-4",
                    "ir_json": VALID_IR_JSON,
                    "shots": "1024",
                    "callback_url": "https://example.com/callback",
                },
            )
        )
        await runner.started.wait()
        mock_redis._values["qpu:job:cancelled:job-4"] = "1"
        await task

        assert runner.cancel_calls == 1
        mock_webhook.send_result.assert_not_called()
        mock_webhook.send_error.assert_not_called()
        assert "msg-inflight-cancel" in mock_redis._acked
        assert mock_redis._hashes["qpu:job:job-4:status"]["state"] == "cancelled"
        assert consumer.current_job_id is None

    async def test_failed_job_sends_error(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_runner.run.side_effect = RuntimeError("backend timeout")
        await consumer._process_message(
            "msg-3",
            {
                "job_id": "job-2",
                "ir_json": VALID_IR_JSON,
                "shots": "1024",
                "callback_url": "https://example.com/callback",
            },
        )
        mock_webhook.send_error.assert_called_once()
        assert mock_redis._hashes["qpu:job:job-2:status"]["state"] == "failed"

    async def test_idle_event_set_after_job(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
    ) -> None:
        assert consumer._idle_event.is_set()
        await consumer._process_message(
            "msg-4",
            {
                "job_id": "job-3",
                "ir_json": VALID_IR_JSON,
                "shots": "1024",
                "callback_url": "https://example.com/callback",
            },
        )
        assert consumer._idle_event.is_set()
        assert consumer.current_job_id is None

    async def test_processes_job_with_byte_keys(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        """Byte-keyed messages (from non-decode_responses clients) are handled."""
        await consumer._process_message(
            "msg-bytes",
            {
                b"job_id": b"job-bytes",
                b"ir_json": VALID_IR_JSON.encode(),
                b"shots": b"1024",
                b"callback_url": b"https://example.com/callback",
            },
        )
        mock_runner.run.assert_called_once()
        mock_webhook.send_result.assert_called_once()
        assert "msg-bytes" in mock_redis._acked

    async def test_malformed_message_acked_and_skipped(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
    ) -> None:
        """Messages missing required fields are ACK-ed and skipped."""
        await consumer._process_message(
            "msg-bad",
            {"ir_json": VALID_IR_JSON, "shots": "1024"},
        )
        mock_runner.run.assert_not_called()
        assert "msg-bad" in mock_redis._acked


class TestBatchConsumer:
    def test_can_batch_when_executor_supports_batch_run(
        self,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_runner.batch_run = AsyncMock(return_value=[])

        consumer = RedisConsumer(
            redis=cast(aioredis.Redis, mock_redis),
            runner=mock_runner,
            webhook=mock_webhook,
            qpu_id="test-node",
        )

        assert consumer._can_batch is True

    def test_cannot_batch_without_batch_run(
        self,
        mock_redis: MockRedis,
        mock_webhook: AsyncMock,
    ) -> None:
        runner = AsyncMock(spec=["run"])

        consumer = RedisConsumer(
            redis=cast(aioredis.Redis, mock_redis),
            runner=runner,
            webhook=mock_webhook,
            qpu_id="test-node",
        )

        assert consumer._can_batch is False

    async def test_processes_batch_and_sends_webhooks(
        self,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_runner.batch_run = AsyncMock(
            return_value=[
                ExecutionResult(
                    counts={"00": 1024},
                    execution_time_ms=150.0,
                    shots_completed=1024,
                ),
                ExecutionResult(
                    counts={"11": 512},
                    execution_time_ms=160.0,
                    shots_completed=512,
                ),
            ]
        )
        consumer = RedisConsumer(
            redis=cast(aioredis.Redis, mock_redis),
            runner=mock_runner,
            webhook=mock_webhook,
            qpu_id="test-node",
        )

        task = await consumer._process_batch(
            [
                (
                    "msg-1",
                    {
                        "job_id": "job-1",
                        "ir_json": VALID_IR_JSON,
                        "shots": "1024",
                        "callback_url": "https://example.com/callback-1",
                    },
                ),
                (
                    "msg-2",
                    {
                        "job_id": "job-2",
                        "ir_json": VALID_IR_JSON,
                        "shots": "512",
                        "callback_url": "https://example.com/callback-2",
                    },
                ),
            ]
        )
        assert task is not None
        await task

        mock_runner.batch_run.assert_awaited_once()
        mock_runner.run.assert_not_called()
        assert mock_webhook.send_result.await_count == 2
        assert mock_redis._hashes["qpu:job:job-1:status"]["state"] == "completed"
        assert mock_redis._hashes["qpu:job:job-2:status"]["state"] == "completed"
        assert sorted(mock_redis._acked) == ["msg-1", "msg-2"]

    async def test_batch_falls_back_to_single_job_processing_on_batch_error(
        self,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_runner.batch_run = AsyncMock(side_effect=RuntimeError("batch failed"))
        consumer = RedisConsumer(
            redis=cast(aioredis.Redis, mock_redis),
            runner=mock_runner,
            webhook=mock_webhook,
            qpu_id="test-node",
        )

        task = await consumer._process_batch(
            [
                (
                    "msg-1",
                    {
                        "job_id": "job-1",
                        "ir_json": VALID_IR_JSON,
                        "shots": "1024",
                        "callback_url": "https://example.com/callback-1",
                    },
                ),
                (
                    "msg-2",
                    {
                        "job_id": "job-2",
                        "ir_json": VALID_IR_JSON,
                        "shots": "1024",
                        "callback_url": "https://example.com/callback-2",
                    },
                ),
            ]
        )
        assert task is None

        mock_runner.batch_run.assert_awaited_once()
        assert mock_runner.run.await_count == 2
        assert mock_webhook.send_result.await_count == 2
        assert sorted(mock_redis._acked) == ["msg-1", "msg-2"]

    async def test_batch_skips_cancelled_job_before_execution(
        self,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_runner.batch_run = AsyncMock(
            return_value=[
                ExecutionResult(
                    counts={"00": 1024},
                    execution_time_ms=150.0,
                    shots_completed=1024,
                )
            ]
        )
        mock_redis._values["qpu:job:cancelled:job-2"] = "1"
        consumer = RedisConsumer(
            redis=cast(aioredis.Redis, mock_redis),
            runner=mock_runner,
            webhook=mock_webhook,
            qpu_id="test-node",
        )

        task = await consumer._process_batch(
            [
                (
                    "msg-1",
                    {
                        "job_id": "job-1",
                        "ir_json": VALID_IR_JSON,
                        "shots": "1024",
                        "callback_url": "https://example.com/callback-1",
                    },
                ),
                (
                    "msg-2",
                    {
                        "job_id": "job-2",
                        "ir_json": VALID_IR_JSON,
                        "shots": "1024",
                        "callback_url": "https://example.com/callback-2",
                    },
                ),
            ]
        )
        assert task is not None
        await task

        mock_runner.batch_run.assert_awaited_once()
        batch_jobs = mock_runner.batch_run.await_args.args[0]
        assert len(batch_jobs) == 1
        assert mock_webhook.send_result.await_count == 1
        assert mock_redis._hashes["qpu:job:job-2:status"]["state"] == "cancelled"
        assert sorted(mock_redis._acked) == ["msg-1", "msg-2"]


class _MockRedisWithPending(MockRedis):
    """MockRedis that returns a single recently-stuck pending message."""

    def __init__(self, pending_fields: dict[str, str]) -> None:
        super().__init__()
        self._pending_fields = pending_fields

    async def xpending_range(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min: str,
        max: str,
        count: int,
    ) -> list[dict[str, str | int]]:
        return [{"message_id": "msg-pending", "time_since_delivered": 500}]

    async def xrange(
        self, stream: str, min: str, max: str
    ) -> list[tuple[str, dict[str, str]]]:
        return [("msg-pending", self._pending_fields)]


class TestRecoverPending:
    async def test_recovers_all_pending_regardless_of_idle_time(
        self,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        """Pending messages for this consumer are recovered even if freshly stuck."""
        pending_fields = {
            "job_id": "job-pending",
            "ir_json": VALID_IR_JSON,
            "shots": "1024",
            "callback_url": "https://example.com/callback",
        }
        redis = _MockRedisWithPending(pending_fields)

        consumer = RedisConsumer(
            redis=cast(aioredis.Redis, redis),
            runner=mock_runner,
            webhook=mock_webhook,
            qpu_id="test-node",
            crash_recovery_threshold_ms=60_000,
        )
        recovered = await consumer.recover_pending()
        assert recovered == 1
        mock_runner.run.assert_called_once()
        assert "msg-pending" in redis._acked


class TestDrain:
    async def test_drain_returns_true_when_idle(
        self,
        consumer: RedisConsumer,
    ) -> None:
        result = await consumer.drain(timeout=0.1)
        assert result is True
        assert consumer._running is False

    async def test_drain_returns_false_on_timeout(
        self,
        consumer: RedisConsumer,
    ) -> None:
        consumer._idle_event.clear()
        result = await consumer.drain(timeout=0.05)
        assert result is False
        assert consumer._running is False
