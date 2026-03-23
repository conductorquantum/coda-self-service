"""Tests for the FastAPI application surface."""

import asyncio
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from self_service.server.app import _resolve_connectivity
from self_service.vpn import ServiceState


@contextmanager
def _make_app(
    vpn_state: ServiceState = ServiceState.READY,
    redis_healthy: bool = True,
    current_job_id: str | None = None,
) -> Iterator[TestClient]:
    """Create a test app with mocked state (no real service connections)."""
    # Use pure mocks to avoid any real VPNGuard behavior
    guard = MagicMock()
    guard.state = vpn_state
    guard.is_ready = vpn_state == ServiceState.READY

    consumer = MagicMock()
    consumer.redis_healthy = redis_healthy
    consumer.current_job_id = current_job_id

    @asynccontextmanager
    async def mock_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.guard = guard
        app.state.consumer = consumer
        app.state.settings = MagicMock()
        app.state.webhook = AsyncMock()
        yield

    app = FastAPI(title="Coda Self-Service Test", lifespan=mock_lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        async def _check_readiness() -> dict[str, object]:
            vpn_ok = request.app.state.guard.is_ready
            redis_ok = request.app.state.consumer.redis_healthy
            return {
                "ready": vpn_ok and redis_ok,
                "vpn_state": request.app.state.guard.state.value,
                "redis_healthy": redis_ok,
                "current_job": request.app.state.consumer.current_job_id,
            }

        try:
            result = await asyncio.wait_for(_check_readiness(), timeout=5.0)
            status_code = 200 if result["ready"] else 503
            return JSONResponse(content=result, status_code=status_code)
        except TimeoutError:
            return JSONResponse(
                content={"ready": False, "reason": "health check timeout"},
                status_code=503,
            )

    # Use TestClient as context manager to ensure lifespan runs
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_health_endpoint() -> None:
    with _make_app() as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_ready_endpoint_healthy() -> None:
    with _make_app(current_job_id="job-123") as client:
        response = client.get("/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert body["vpn_state"] == "ready"
        assert body["redis_healthy"] is True
        assert body["current_job"] == "job-123"


def test_ready_endpoint_vpn_down() -> None:
    with _make_app(vpn_state=ServiceState.VPN_UNAVAILABLE) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["vpn_state"] == "vpn_unavailable"


def test_ready_endpoint_redis_unhealthy() -> None:
    with _make_app(redis_healthy=False) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["redis_healthy"] is False


def test_resolve_connectivity_prefers_directed_edges() -> None:
    device = MagicMock()
    device.directed_edges = [(1, 0), (2, 1)]
    device.logical_edges = [(0, 1), (1, 2)]

    assert _resolve_connectivity(device) == [[1, 0], [2, 1]]


def test_resolve_connectivity_falls_back_to_logical_edges() -> None:
    device = MagicMock(spec=["logical_edges"])
    device.logical_edges = [(0, 1), (1, 2)]

    assert _resolve_connectivity(device) == [[0, 1], [1, 2]]


def test_resolve_connectivity_returns_none_without_device() -> None:
    assert _resolve_connectivity(None) is None


def test_resolve_connectivity_falls_back_when_directed_edges_empty() -> None:
    device = MagicMock()
    device.directed_edges = []
    device.logical_edges = [(0, 1), (1, 2)]

    assert _resolve_connectivity(device) == [[0, 1], [1, 2]]
