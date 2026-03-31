"""Tests for webhook payload generation and posting."""

from unittest.mock import AsyncMock, patch

from coda_node.server.webhook import WebhookClient, WebhookPayload


def test_webhook_payload_omits_none_fields() -> None:
    payload = WebhookPayload(job_id="job-1", status="completed")
    assert payload.to_dict() == {"job_id": "job-1", "status": "completed"}


@patch("coda_node.server.webhook.sign_token", return_value="mock-jwt-token")
async def test_send_result_posts_json(_mock_token: AsyncMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    client = WebhookClient("node-1", "mock-private-key", "mock-key-id")
    client._client = mock_client

    payload = WebhookPayload(job_id="job-1", status="completed", counts={"00": 512})
    await client.send_result("https://example.com/callback", payload)

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://example.com/callback"
    assert call_args[1]["headers"]["Authorization"] == "Bearer mock-jwt-token"


@patch("coda_node.server.webhook.sign_token", return_value="mock-jwt-token")
async def test_send_result_includes_extra_headers(_mock_token: AsyncMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    client = WebhookClient(
        "node-1",
        "mock-private-key",
        "mock-key-id",
        extra_headers={"x-vercel-protection-bypass": "secret123"},
    )
    client._client = mock_client

    payload = WebhookPayload(job_id="job-1", status="completed")
    await client.send_result("https://example.com/callback", payload)

    headers = mock_client.post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer mock-jwt-token"
    assert headers["x-vercel-protection-bypass"] == "secret123"


@patch("coda_node.server.webhook.sign_token", return_value="mock-jwt-token")
async def test_send_error_convenience(_mock_token: AsyncMock) -> None:
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    client = WebhookClient("node-1", "mock-private-key", "mock-key-id")
    client._client = mock_client

    await client.send_error("https://example.com/callback", "job-1", "boom")

    body = mock_client.post.call_args[1]["json"]
    assert body["status"] == "failed"
    assert body["error"] == "boom"
