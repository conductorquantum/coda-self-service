"""Tests for the periodic heartbeat reporter."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from self_service.server.heartbeat import HeartbeatClient


def _make_consumer(**overrides: object) -> MagicMock:
    """Create a mock RedisConsumer with default attributes."""
    consumer = MagicMock()
    consumer.current_job_id = overrides.get("current_job_id")
    consumer.last_job_at = overrides.get("last_job_at")
    consumer.redis_healthy = overrides.get("redis_healthy", True)
    return consumer


@patch("self_service.server.heartbeat.sign_token", return_value="mock-jwt")
def test_send_posts_authenticated_payload(_mock_sign: MagicMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    consumer = _make_consumer(current_job_id="job-42", redis_healthy=True)
    client = HeartbeatClient(
        heartbeat_url="https://example.com/api/internal/qpu/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
    )
    client._client = mock_http

    asyncio.run(client._send())

    call_args = mock_http.post.call_args
    assert call_args[0][0] == "https://example.com/api/internal/qpu/heartbeat"
    assert call_args[1]["headers"]["Authorization"] == "Bearer mock-jwt"

    body = call_args[1]["json"]
    assert body["current_job"] == "job-42"
    assert body["redis_healthy"] is True


@patch("self_service.server.heartbeat.sign_token", return_value="mock-jwt")
def test_send_includes_idle_state(_mock_sign: MagicMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    consumer = _make_consumer(
        current_job_id=None,
        last_job_at="2026-03-19T12:00:00+00:00",
        redis_healthy=False,
    )
    client = HeartbeatClient(
        heartbeat_url="https://example.com/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
    )
    client._client = mock_http

    asyncio.run(client._send())

    body = mock_http.post.call_args[1]["json"]
    assert body["current_job"] is None
    assert body["last_job_at"] == "2026-03-19T12:00:00+00:00"
    assert body["redis_healthy"] is False


@patch("self_service.server.heartbeat.sign_token", return_value="mock-jwt")
def test_send_includes_connectivity(_mock_sign: MagicMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    consumer = _make_consumer()
    client = HeartbeatClient(
        heartbeat_url="https://example.com/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
        connectivity=[[0, 1], [1, 2]],
    )
    client._client = mock_http

    asyncio.run(client._send())

    body = mock_http.post.call_args[1]["json"]
    assert body["connectivity"] == [[0, 1], [1, 2]]


@patch("self_service.server.heartbeat.sign_token", return_value="mock-jwt")
def test_send_connectivity_none_when_not_provided(_mock_sign: MagicMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    consumer = _make_consumer()
    client = HeartbeatClient(
        heartbeat_url="https://example.com/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
    )
    client._client = mock_http

    asyncio.run(client._send())

    body = mock_http.post.call_args[1]["json"]
    assert body["connectivity"] is None


@patch("self_service.server.heartbeat.sign_token", return_value="mock-jwt")
def test_run_loop_sends_and_stops(_mock_sign: MagicMock) -> None:
    """Verify the run loop sends at least one heartbeat then stops."""
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.aclose = AsyncMock()

    consumer = _make_consumer()
    client = HeartbeatClient(
        heartbeat_url="https://example.com/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
        interval=0,
    )
    client._client = mock_http

    async def _run_briefly() -> int:
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.05)
        client.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return int(mock_http.post.call_count)

    call_count = asyncio.run(_run_briefly())
    assert call_count >= 1


@patch("self_service.server.heartbeat.sign_token", return_value="mock-jwt")
def test_send_failure_does_not_crash_loop(_mock_sign: MagicMock) -> None:
    """A failed heartbeat POST should be logged, not raised."""
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=Exception("network down"))
    mock_http.aclose = AsyncMock()

    consumer = _make_consumer()
    client = HeartbeatClient(
        heartbeat_url="https://example.com/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
        interval=0,
    )
    client._client = mock_http

    async def _run_briefly() -> None:
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.05)
        client.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run_briefly())
    assert mock_http.post.call_count >= 1


@pytest.mark.asyncio
async def test_close_stops_and_closes_http() -> None:
    mock_http = AsyncMock()
    mock_http.aclose = AsyncMock()

    consumer = _make_consumer()
    client = HeartbeatClient(
        heartbeat_url="https://example.com/heartbeat",
        qpu_id="qpu-1",
        jwt_private_key="fake-key",
        jwt_key_id="kid-1",
        consumer=consumer,
    )
    client._client = mock_http

    await client.close()

    assert client._running is False
    mock_http.aclose.assert_awaited_once()
