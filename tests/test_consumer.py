"""Tests for the Redis stream consumer."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis

from self_service.server.consumer import RedisConsumer
from self_service.server.executor import ExecutionResult


class MockRedis:
    def __init__(self) -> None:
        self._groups_created: set[str] = set()
        self._acked: list[str] = []
        self._hashes: dict[str, dict[str, str]] = {}

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
    def test_setup_creates_group(
        self, consumer: RedisConsumer, mock_redis: MockRedis
    ) -> None:
        asyncio.run(consumer.setup())
        assert "qpu:test-node:workers" in mock_redis._groups_created

    def test_processes_successful_job(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        asyncio.run(
            consumer._process_message(
                "msg-1",
                {
                    "job_id": "job-1",
                    "ir_json": VALID_IR_JSON,
                    "shots": "1024",
                    "callback_url": "https://example.com/callback",
                },
            )
        )
        mock_runner.run.assert_called_once()
        mock_webhook.send_result.assert_called_once()
        assert "msg-1" in mock_redis._acked

    def test_skips_completed_job(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
    ) -> None:
        mock_redis._hashes["qpu:job:job-1:status"] = {"state": "completed"}
        asyncio.run(
            consumer._process_message(
                "msg-2",
                {
                    "job_id": "job-1",
                    "ir_json": VALID_IR_JSON,
                    "shots": "1024",
                    "callback_url": "https://example.com/callback",
                },
            )
        )
        mock_runner.run.assert_not_called()
        assert "msg-2" in mock_redis._acked

    def test_failed_job_sends_error(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        mock_runner.run.side_effect = RuntimeError("backend timeout")
        asyncio.run(
            consumer._process_message(
                "msg-3",
                {
                    "job_id": "job-2",
                    "ir_json": VALID_IR_JSON,
                    "shots": "1024",
                    "callback_url": "https://example.com/callback",
                },
            )
        )
        mock_webhook.send_error.assert_called_once()
        assert mock_redis._hashes["qpu:job:job-2:status"]["state"] == "failed"

    def test_idle_event_set_after_job(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
    ) -> None:
        assert consumer._idle_event.is_set()
        asyncio.run(
            consumer._process_message(
                "msg-4",
                {
                    "job_id": "job-3",
                    "ir_json": VALID_IR_JSON,
                    "shots": "1024",
                    "callback_url": "https://example.com/callback",
                },
            )
        )
        assert consumer._idle_event.is_set()
        assert consumer.current_job_id is None

    def test_processes_job_with_byte_keys(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
        mock_webhook: AsyncMock,
    ) -> None:
        """Byte-keyed messages (from non-decode_responses clients) are handled."""
        asyncio.run(
            consumer._process_message(
                "msg-bytes",
                {
                    b"job_id": b"job-bytes",
                    b"ir_json": VALID_IR_JSON.encode(),
                    b"shots": b"1024",
                    b"callback_url": b"https://example.com/callback",
                },
            )
        )
        mock_runner.run.assert_called_once()
        mock_webhook.send_result.assert_called_once()
        assert "msg-bytes" in mock_redis._acked

    def test_malformed_message_acked_and_skipped(
        self,
        consumer: RedisConsumer,
        mock_redis: MockRedis,
        mock_runner: AsyncMock,
    ) -> None:
        """Messages missing required fields are ACK-ed and skipped."""
        asyncio.run(
            consumer._process_message(
                "msg-bad",
                {"ir_json": VALID_IR_JSON, "shots": "1024"},
            )
        )
        mock_runner.run.assert_not_called()
        assert "msg-bad" in mock_redis._acked


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
    def test_recovers_all_pending_regardless_of_idle_time(
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
        recovered = asyncio.run(consumer.recover_pending())
        assert recovered == 1
        mock_runner.run.assert_called_once()
        assert "msg-pending" in redis._acked


class TestDrain:
    def test_drain_returns_true_when_idle(
        self,
        consumer: RedisConsumer,
    ) -> None:
        result = asyncio.run(consumer.drain(timeout=0.1))
        assert result is True
        assert consumer._running is False

    def test_drain_returns_false_on_timeout(
        self,
        consumer: RedisConsumer,
    ) -> None:
        consumer._idle_event.clear()
        result = asyncio.run(consumer.drain(timeout=0.05))
        assert result is False
        assert consumer._running is False
