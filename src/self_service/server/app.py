"""FastAPI application for the standalone Coda-connected node server.

The application is constructed via :func:`create_app`, which wires up a
lifespan that boots the VPN guard, Redis consumer, and webhook client.
A module-level ``app`` instance is provided for ``uvicorn`` import-string
references (``self_service.server.app:app``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from self_service.server.config import Settings
from self_service.server.consumer import RedisConsumer
from self_service.server.executor import JobExecutor, load_executor
from self_service.server.webhook import WebhookClient
from self_service.vpn import (
    ServiceState,
    VPNGuard,
    connect_settings,
    kill_openvpn_daemon,
)

logger = logging.getLogger(__name__)


async def _on_vpn_state_change(state: ServiceState) -> None:
    """Log VPN state transitions at WARNING level."""
    logger.warning("VPN state changed: %s", state.value)


def create_app(executor: JobExecutor | None = None) -> FastAPI:
    """Build a fully-wired FastAPI application.

    The returned app uses an async lifespan that:

    1. Loads ``Settings`` from environment / persisted config.
    2. Connects to the Coda cloud (bootstrap or JWT reconnect).
    3. Runs a VPN preflight check and starts background monitoring.
    4. Opens a Redis consumer loop that dispatches jobs to *executor*.
    5. On shutdown, drains in-flight work and tears down resources.

    Args:
        executor: Custom execution backend.  When ``None``, the executor
            is resolved from ``CODA_EXECUTOR_FACTORY`` or falls back to
            :class:`~self_service.server.executor.NoopExecutor`.

    Returns:
        A configured :class:`~fastapi.FastAPI` instance with ``/health``
        and ``/ready`` endpoints.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = Settings()
        await connect_settings(settings)

        guard = VPNGuard(
            probe_targets=settings.vpn_probe_urls,
            interface_hint=settings.vpn_interface_hint,
            check_interval_sec=settings.vpn_check_interval_sec,
            vpn_required=settings.vpn_required,
        )
        vpn_status = await guard.preflight()
        if (
            not vpn_status.ok
            and settings.vpn_required
            and not settings.allow_degraded_startup
        ):
            raise RuntimeError(f"VPN preflight failed: {vpn_status.reason}")

        redis_client = aioredis.from_url(settings.redis_url)
        runner = executor or load_executor(settings)
        webhook = WebhookClient(
            qpu_id=settings.qpu_id,
            jwt_private_key=settings.jwt_private_key,
            jwt_key_id=settings.jwt_key_id,
        )
        consumer = RedisConsumer(
            redis=redis_client,
            runner=runner,
            webhook=webhook,
            qpu_id=settings.qpu_id,
        )

        watch_task = asyncio.create_task(guard.watch(_on_vpn_state_change))
        consumer_task = asyncio.create_task(consumer.consume_loop())

        app.state.settings = settings
        app.state.guard = guard
        app.state.consumer = consumer
        app.state.webhook = webhook

        yield

        guard.stop()
        watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await watch_task

        drained = await consumer.drain(timeout=settings.shutdown_drain_timeout_sec)
        if not drained:
            logger.warning("Drain timeout expired, cancelling in-flight job")
        consumer_task.cancel()
        with suppress(asyncio.CancelledError):
            await consumer_task

        await webhook.close()
        await redis_client.aclose()
        kill_openvpn_daemon()

    app = FastAPI(title="Coda Self-Service", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe — returns 200 if the process is running."""
        return {"status": "ok"}

    async def _check_readiness() -> dict[str, object]:
        """Gather composite readiness state from VPN guard and Redis consumer."""
        guard: VPNGuard = app.state.guard
        consumer: RedisConsumer = app.state.consumer
        vpn_ok = guard.is_ready
        redis_ok = consumer.redis_healthy
        return {
            "ready": vpn_ok and redis_ok,
            "vpn_state": guard.state.value,
            "redis_healthy": redis_ok,
            "current_job": consumer.current_job_id,
        }

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """Readiness probe — returns 200 when healthy, 503 otherwise."""
        try:
            result = await asyncio.wait_for(_check_readiness(), timeout=5.0)
            status_code = 200 if result["ready"] else 503
            return JSONResponse(content=result, status_code=status_code)
        except TimeoutError:
            return JSONResponse(
                content={"ready": False, "reason": "health check timeout"},
                status_code=503,
            )

    return app


app = create_app()
