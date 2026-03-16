"""Tests for the FastAPI application surface."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from self_service.server.app import create_app
from self_service.vpn import ServiceState, VPNGuard


def _make_app(
    vpn_state: ServiceState = ServiceState.READY,
    redis_healthy: bool = True,
    current_job_id: str | None = None,
) -> TestClient:
    app = create_app()
    guard = VPNGuard(vpn_required=False)
    guard._state = vpn_state
    consumer = MagicMock()
    consumer.redis_healthy = redis_healthy
    consumer.current_job_id = current_job_id
    app.state.guard = guard
    app.state.consumer = consumer
    app.state.settings = MagicMock()
    app.state.webhook = AsyncMock()
    return TestClient(app, raise_server_exceptions=False)


def test_health_endpoint() -> None:
    client = _make_app()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_endpoint_healthy() -> None:
    client = _make_app(current_job_id="job-123")
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["vpn_state"] == "ready"
    assert body["redis_healthy"] is True
    assert body["current_job"] == "job-123"


def test_ready_endpoint_vpn_down() -> None:
    client = _make_app(vpn_state=ServiceState.VPN_UNAVAILABLE)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["vpn_state"] == "vpn_unavailable"


def test_ready_endpoint_redis_unhealthy() -> None:
    client = _make_app(redis_healthy=False)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["redis_healthy"] is False
